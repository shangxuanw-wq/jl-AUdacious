"""資料庫連線。Serverless 環境：不留連線池（NullPool），每個請求自己開關。

Supabase 連線字串直接貼原本的 postgresql://... 即可，這裡會轉成 asyncpg。
建議用 Session pooler（aws-*.pooler.supabase.com:5432，IPv4）。
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from . import config

_engine: AsyncEngine | None = None
_engine_url: str | None = None


def _asyncpg_url(url: str) -> str:
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    return url


def engine() -> AsyncEngine:
    global _engine, _engine_url
    url = config.settings.database_url
    if not url:
        raise RuntimeError("RFQ_DATABASE_URL 沒有設定")
    if _engine is None or _engine_url != url:
        host = urlparse(_asyncpg_url(url).replace("+asyncpg", "")).hostname or ""
        connect_args: dict = {
            # 經過 Supavisor 時不要用固定名稱的 prepared statement
            "statement_cache_size": 0,
            "prepared_statement_name_func": lambda: f"__rfq_{uuid.uuid4().hex}__",
        }
        if host.endswith("supabase.com") or host.endswith("supabase.co"):
            connect_args["ssl"] = "require"
        _engine = create_async_engine(_asyncpg_url(url), poolclass=NullPool, connect_args=connect_args)
        _engine_url = url
    return _engine


@asynccontextmanager
async def tx() -> AsyncIterator[AsyncConnection]:
    """一個 transaction；離開時 commit，例外時 rollback。"""
    async with engine().begin() as conn:
        yield conn


async def dispose() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
