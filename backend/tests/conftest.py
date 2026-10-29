import os
import sys
from pathlib import Path

import httpx
import pytest

TOKEN = "mock-token-0123456789-abcdefghij"
BASE = "http://testserver"

os.environ.update(
    {
        "RFQ_DATABASE_URL": os.environ.get("TEST_DATABASE_URL", "postgresql://postgres@127.0.0.1:55432/rfq_test"),
        "RFQ_DEV_LOGIN_EMAIL": "tester@example.com",
        "MOCK_AUD_TOKEN": TOKEN,
        "AUD_QUOTE_API_TOKEN": TOKEN,
        "AUD_QUOTE_API_URL": BASE + "/api/mock-aud/api/rfq/quotes",
        "APP_BASE_URL": BASE,
        "SESSION_SECRET": "test-session-secret",
        "RFQ_INLINE_RETRY_SECONDS": "0",
    }
)
os.environ.pop("VERCEL", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import app  # noqa: E402
from rfq_app import config, db, dispatcher  # noqa: E402
from sqlalchemy import text  # noqa: E402


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    config.reload_settings()
    dispatcher.client_factory = lambda: httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE, timeout=30)
    async with db.tx() as conn:
        await conn.execute(text("TRUNCATE rfq.dispatch_attempts, rfq.quote_dispatches, rfq.quote_items, rfq.quotes, rfq.inbound_messages, rfq.mailboxes, rfq.rfqs, rfq.quote_no_counters RESTART IDENTITY CASCADE"))
        await conn.execute(text("DELETE FROM mock_partner.rfqs WHERE number NOT IN ('AUD-RFQ-2026-0099','AUD-RFQ-2026-0098','AUD-RFQ-2026-0097','AUD-RFQ-2026-0096','AUD-RFQ-2026-0095','AUD-RFQ-2026-0094')"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as c:
        r = await c.post("/api/mock-aud/_admin/reset")
        assert r.status_code == 200
        yield c
    await db.dispose()
