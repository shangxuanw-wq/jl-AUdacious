"""Vercel Queues：送出報價的背景處理。

佇列只負責「什麼時候再來一次」；狀態一律以資料庫為準，所以重複投遞也安全。
"""

from __future__ import annotations

import logging

from pydantic import BaseModel
from vercel.queue import Message, RetryAfter, Topic, send, subscribe

from . import config, dispatcher

log = logging.getLogger("rfq.queue")


class DispatchJob(BaseModel):
    dispatch_id: int


dispatch_topic = Topic[DispatchJob]("quote-dispatch")


@subscribe(topic=dispatch_topic, consumer_group="sender", max_concurrency=5)
async def handle_dispatch(message: Message[DispatchJob]) -> None:
    result = await dispatcher.process_dispatch(message.payload.dispatch_id)
    if result.retry_in is not None:
        raise RetryAfter(max(1, int(result.retry_in)))


async def enqueue(dispatch_id: int, key: str = "send") -> str:
    """丟進佇列；本機（不在 Vercel）或佇列失敗時，直接就地處理一次。回傳 'queued' 或處理結果。

    key 用來防止同一個動作重複排入（例如按了兩次送出）；手動重新排入要給不同的 key。
    """
    if config.settings.on_vercel:
        try:
            await send(dispatch_topic, DispatchJob(dispatch_id=dispatch_id), idempotency_key=f"dispatch-{dispatch_id}-{key}")
            return "queued"
        except Exception:  # noqa: BLE001 - 佇列故障時退回就地處理
            log.exception("enqueue failed for dispatch %s; processing inline", dispatch_id)
    result = await dispatcher.process_dispatch(dispatch_id)
    return result.state
