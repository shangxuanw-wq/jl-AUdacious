"""估價模組後端（Vercel Services 的 backend service，入口 main:app）。"""

from __future__ import annotations

import logging
import secrets

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text
from starlette.middleware.sessions import SessionMiddleware

from rfq_app import config, db, queue_worker
from rfq_app.auth import router as auth_router
from rfq_app.mock_aud.routes import admin as mock_admin_router
from rfq_app.mock_aud.routes import router as mock_router
from rfq_app.routers.rfqs import router as rfq_router
from rfq_app.selftest import router as selftest_router
from rfq_app.mail import ingest as mail_ingest
from rfq_app.mail.routes import files as mail_files_router
from rfq_app.mail.routes import router as mail_router

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="JL × 澳得仕 估價模組", docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def ensure_api_prefix(request: Request, call_next):
    # 不論平台轉送時有沒有去掉 /api 前綴，路由都對得上
    path = request.scope.get("path", "")
    if not path.startswith("/api/") and path != "/api":
        request.scope["path"] = "/api" + (path if path.startswith("/") else "/" + path)
    return await call_next(request)


@app.middleware("http")
async def queue_push(request: Request, call_next):
    # Vercel Queues 推送：不論推到哪個路徑，都交給佇列 SDK 處理（認證資訊在推送的標頭裡）
    if request.headers.get("ce-type") == queue_worker.PUSH_EVENT_TYPE:
        body = await request.body()
        try:
            await queue_worker.accept_push(body, request.headers)
        except Exception:  # noqa: BLE001
            logging.getLogger("rfq.queue").exception("queue push failed (path %s)", request.url.path)
            return Response(status_code=500)
        return Response(status_code=200)
    return await call_next(request)


app.add_middleware(
    SessionMiddleware,
    secret_key=config.settings.session_secret or secrets.token_hex(32),
    session_cookie="rfq_session",
    max_age=7 * 24 * 3600,
    same_site="lax",
    https_only=config.settings.on_vercel,
)

app.include_router(auth_router)
app.include_router(rfq_router)
app.include_router(mock_router)
app.include_router(mock_admin_router)


@app.middleware("http")
async def mock_switch(request: Request, call_next):
    # 假澳得仕關掉時，整組 /api/mock-aud/* 都當作不存在
    if request.scope.get("path", "").startswith(("/api/mock-aud", "/mock-aud")) and not config.settings.mock_enabled:
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    return await call_next(request)
app.include_router(selftest_router)
app.include_router(mail_router)
app.include_router(mail_files_router)


@app.get("/api/health")
async def health() -> dict:
    s = config.settings
    db_ok = False
    db_error = None
    try:
        async with db.tx() as conn:
            db_ok = (await conn.execute(text("SELECT count(*) FROM rfq.schema_migrations"))).scalar_one() >= 2
    except Exception as e:  # noqa: BLE001
        db_error = type(e).__name__
    return {
        "ok": db_ok,
        "db": db_ok,
        "db_error": db_error,
        "worker_enabled": s.worker_enabled,
        "login_configured": s.google_login_configured or s.key_login_configured,
        "google_login": s.google_login_configured,
        "key_login": s.key_login_configured,
        "session_secret_set": bool(s.session_secret),
        "selftest_enabled": len(s.selftest_key) >= 24,
        "mail_configured": s.mail_configured,
        "mock_token_configured": len(s.mock_aud_token) >= 24,
        "on_vercel": s.on_vercel,
    }


@app.get("/api/cron/sweep")
async def cron_sweep(request: Request) -> dict:
    # Vercel Cron 會帶 Authorization: Bearer $CRON_SECRET
    secret = config.settings.cron_secret
    if len(secret) < 16 or not secrets.compare_digest(request.headers.get("authorization", ""), f"Bearer {secret}"):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    out = {"processed": await queue_worker.sweep()}
    if config.settings.mail_configured:
        try:
            out["mail"] = await mail_ingest.poll()
        except Exception as e:  # noqa: BLE001 - 收信失敗不影響重送
            out["mail"] = {"error": type(e).__name__}
    return out


@app.exception_handler(RuntimeError)
async def runtime_error(_: Request, exc: RuntimeError) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=503)
