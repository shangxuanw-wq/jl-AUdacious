"""送出報價的背景處理。

狀態一律以資料庫為準（重複處理也安全），排程有三條路，任何一條到了都會照資料庫的
next_attempt_at 決定要不要真的送：

1. 按「送出」時就地送第 1 次（馬上知道結果）。
2. 需要重送時丟一則「延遲 N 秒才可見」的訊息到 Vercel Queues（topic: quote-dispatch），
   佇列推送進來時（main.py 的中介層轉給 accept_push）再處理一次。
3. 掃描（sweep）：把到期的送出紀錄找出來處理。人員介面在有送出中的報價時會呼叫，
   每天的 Vercel Cron 也會呼叫一次當保險。
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta
from typing import Mapping

from pydantic import BaseModel
from sqlalchemy import text
from vercel.queue import Message, RetryAfter, Topic, accept_and_handle, send, subscribe

from . import config, db, dispatcher

log = logging.getLogger("rfq.queue")

PUSH_EVENT_TYPE = "com.vercel.queue.v2beta"


class DispatchJob(BaseModel):
    dispatch_id: int


dispatch_topic = Topic[DispatchJob]("quote-dispatch")


async def _handle(message: Message[DispatchJob]) -> None:
    result = await dispatcher.process_dispatch(message.payload.dispatch_id)
    log.info("queue delivery dispatch %s -> %s", message.payload.dispatch_id, result.state)
    if result.retry_in is not None:
        raise RetryAfter(max(1, int(result.retry_in)))


@subscribe(topic=dispatch_topic, consumer_group="sender", max_concurrency=5)
async def handle_dispatch(message: Message[DispatchJob]) -> None:
    await _handle(message)


_groups = {"sender"}


def _ensure_consumer_group(group: str) -> None:
    """平台推送的 consumer group 名稱不一定是 sender；第一次看到就補註冊一個同樣的處理函式。"""
    if not group or group in _groups:
        return

    async def _h(message: Message[DispatchJob]) -> None:
        await _handle(message)

    _h.__name__ = _h.__qualname__ = f"handle_dispatch_g{len(_groups)}"
    subscribe(topic=dispatch_topic, consumer_group=group)(_h)
    _groups.add(group)
    log.info("registered queue consumer group %s", group)


async def accept_push(body: bytes, headers: Mapping[str, str]) -> None:
    _ensure_consumer_group(headers.get("ce-vqsconsumergroup", ""))
    await accept_and_handle(body, dict(headers))


async def _schedule(dispatch_id: int, delay: float, key: str) -> bool:
    if not config.settings.on_vercel:
        return False
    try:
        await send(
            dispatch_topic,
            DispatchJob(dispatch_id=dispatch_id),
            idempotency_key=f"dispatch-{dispatch_id}-{key}",
            delay=timedelta(seconds=max(0, int(delay))),
        )
        return True
    except Exception:  # noqa: BLE001 - 佇列故障時還有 sweep
        log.exception("queue send failed for dispatch %s", dispatch_id)
        return False


async def enqueue(dispatch_id: int, key: str = "send") -> str:
    """就地處理；短間隔（2、5、15 秒）的重送也在這裡等，超過預算才交給背景。回傳最後的結果狀態。

    key 用來防止同一個動作重複排入（例如按了兩次送出）；手動重新排入要給不同的 key。
    """
    budget = config.settings.inline_retry_seconds
    t0 = time.monotonic()
    result = await dispatcher.process_dispatch(dispatch_id)
    while result.retry_in is not None and result.retry_in <= 15 and (time.monotonic() - t0) + result.retry_in <= budget:
        await asyncio.sleep(result.retry_in)
        result = await dispatcher.process_dispatch(dispatch_id)
    if result.retry_in is not None:
        await _schedule(dispatch_id, result.retry_in, f"{key}-{result.state}-{int(time.time())}")
    return result.state


async def sweep(limit: int = 20) -> list[dict]:
    """處理所有到期的送出紀錄（待送、等待重送到期、或卡在送出中太久的）。"""
    s = config.settings
    async with db.tx() as conn:
        ids = (
            await conn.execute(
                text(
                    "SELECT id FROM rfq.quote_dispatches WHERE "
                    "(status IN ('pending','retry_wait') AND next_attempt_at <= now()) "
                    "OR (status = 'sending' AND sending_started_at < now() - make_interval(secs => :stale)) "
                    "ORDER BY next_attempt_at LIMIT :lim"
                ),
                {"stale": s.sending_stale_seconds, "lim": limit},
            )
        ).scalars().all()
    out = []
    for did in ids:
        r = await dispatcher.process_dispatch(did)
        if r.retry_in is not None:
            await _schedule(did, r.retry_in, f"sweep-{int(time.time())}")
        out.append({"dispatch_id": did, "state": r.state})
    return out
