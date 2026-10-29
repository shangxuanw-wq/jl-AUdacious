"""設定：全部從環境變數讀，密鑰只放在 Vercel 的環境變數（不寫進程式、不寫進 log）。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

PARTNER_PROD_HOST = "audacious-3d-studio.vercel.app"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class Settings:
    database_url: str
    session_secret: str
    google_client_id: str
    google_client_secret: str
    allowed_emails: frozenset[str]
    app_base_url: str
    aud_quote_api_url: str
    aud_quote_api_token: str
    allow_partner_prod: bool
    mock_aud_token: str
    vendor_name: str
    http_timeout: float
    sending_stale_seconds: int
    on_vercel: bool
    dev_login_email: str
    access_key: str
    selftest_key: str
    cron_secret: str
    inline_retry_seconds: float
    mail_reply_mode: str
    mail_token_key: str
    rfq_mailbox: str
    rfq_sender_allow: frozenset[str]

    @property
    def worker_enabled(self) -> bool:
        return bool(self.aud_quote_api_url and self.aud_quote_api_token)

    @property
    def google_login_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret and self.session_secret and self.allowed_emails)

    @property
    def mail_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret and self.mail_token_key and self.app_base_url)

    @property
    def key_login_configured(self) -> bool:
        # 臨時登入：Google 還沒設定好之前用。金鑰太短一律不啟用
        return bool(self.session_secret and len(self.access_key) >= 24)

    @property
    def target_is_partner_prod(self) -> bool:
        return urlparse(self.aud_quote_api_url).hostname == PARTNER_PROD_HOST


def load_settings() -> Settings:
    base = _env("APP_BASE_URL")
    if not base and _env("VERCEL_PROJECT_PRODUCTION_URL"):
        base = "https://" + _env("VERCEL_PROJECT_PRODUCTION_URL")
    return Settings(
        database_url=_env("RFQ_DATABASE_URL"),
        session_secret=_env("SESSION_SECRET"),
        google_client_id=_env("GOOGLE_CLIENT_ID"),
        google_client_secret=_env("GOOGLE_CLIENT_SECRET"),
        allowed_emails=frozenset(e.strip().lower() for e in _env("ALLOWED_EMAILS").split(",") if e.strip()),
        app_base_url=base.rstrip("/"),
        aud_quote_api_url=_env("AUD_QUOTE_API_URL"),
        aud_quote_api_token=_env("AUD_QUOTE_API_TOKEN"),
        allow_partner_prod=_env("RFQ_ALLOW_PARTNER_PROD").lower() == "true",
        mock_aud_token=_env("MOCK_AUD_TOKEN"),
        vendor_name=_env("RFQ_VENDOR_NAME", "兆臨") or "兆臨",
        http_timeout=float(_env("RFQ_HTTP_TIMEOUT_SECONDS", "30") or 30),
        sending_stale_seconds=int(_env("RFQ_SENDING_STALE_SECONDS", "120") or 120),
        on_vercel=bool(_env("VERCEL")),
        # 只在本機測試用；在 Vercel 上一律忽略
        dev_login_email="" if _env("VERCEL") else _env("RFQ_DEV_LOGIN_EMAIL").lower(),
        access_key=_env("APP_ACCESS_KEY"),
        selftest_key=_env("SELFTEST_KEY"),
        cron_secret=_env("CRON_SECRET"),
        # 送出當下就地重試（2、5、15 秒）最多花多久；超過就交給背景
        # 報價回信寄給誰：live（承辦人）／self（只寄給自己）／off；空的＝送正式站時 live，其他 self
        mail_reply_mode=_env("RFQ_MAIL_REPLY").lower(),
        inline_retry_seconds=float(_env("RFQ_INLINE_RETRY_SECONDS", "45") or 45),
        mail_token_key=_env("MAIL_TOKEN_KEY"),
        rfq_mailbox=(_env("RFQ_MAILBOX", "jl-jimmy@jauhlirn.com") or "jl-jimmy@jauhlirn.com").lower(),
        # 只收這些寄件人（完整信箱或 @網域），逗號分隔；空的 = 不限制
        rfq_sender_allow=frozenset(e.strip().lower() for e in _env("RFQ_SENDER_ALLOW").split(",") if e.strip()),
    )


settings = load_settings()


def reload_settings() -> Settings:
    global settings
    settings = load_settings()
    return settings
