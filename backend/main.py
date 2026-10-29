"""估價模組後端（Vercel Services 的 backend service，入口 main:app）。"""

from __future__ import annotations

import logging
import secrets

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.middleware.sessions import SessionMiddleware

from rfq_app import config, db
from rfq_app.auth import router as auth_router
from rfq_app.mock_aud.routes import admin as mock_admin_router
from rfq_app.mock_aud.routes import router as mock_router
from rfq_app.routers.rfqs import router as rfq_router

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="JL × 澳得仕 估價模組", docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def ensure_api_prefix(request: Request, call_next):
    # 不論平台轉送時有沒有去掉 /api 前綴，路由都對得上
    path = request.scope.get("path", "")
    if not path.startswith("/api/") and path != "/api":
        request.scope["path"] = "/api" + (path if path.startswith("/") else "/" + path)
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
        "login_configured": bool(s.google_client_id and s.google_client_secret and s.session_secret and s.allowed_emails),
        "mock_token_configured": len(s.mock_aud_token) >= 24,
        "on_vercel": s.on_vercel,
    }


@app.exception_handler(RuntimeError)
async def runtime_error(_: Request, exc: RuntimeError) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=503)
