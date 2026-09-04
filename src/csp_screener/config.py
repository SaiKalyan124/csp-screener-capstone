from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = ROOT / "web"

DEFAULT_UNIVERSE = (
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "AVGO", "TSLA",
    "COST", "NFLX", "AMD", "MU", "QCOM", "AMAT", "LRCX", "ADBE",
    "CSCO", "INTC", "PANW", "BKNG", "GILD", "PEP", "SBUX", "INTU",
)


@dataclass(frozen=True)
class Settings:
    alpaca_key: str
    alpaca_secret: str
    supabase_url: str | None = None
    supabase_service_role_key: str | None = None
    supabase_anon_key: str | None = None
    auth_required: bool = False
    weekly_ai_budget_usd: float = 3.0
    allowed_emails: tuple[str, ...] = ()
    universe: tuple[str, ...] = DEFAULT_UNIVERSE
    refresh_seconds: int = 900
    host: str = "127.0.0.1"
    port: int = 8080


def load_settings() -> Settings:
    """Load local and optional shared credentials without leaking them to clients."""
    load_dotenv(ROOT / ".env", override=False)
    shared_env = os.getenv("CSP_SHARED_ENV_FILE")
    if shared_env:
        shared = Path(shared_env).expanduser()
        if shared.exists():
            load_dotenv(shared, override=False)
    def clean_env(name: str) -> str | None:
        value = os.getenv(name)
        cleaned = value.strip() if value else ""
        return cleaned or None

    key = clean_env("ALPACA_API_KEY") or clean_env("APCA_API_KEY_ID")
    secret = clean_env("ALPACA_SECRET_KEY") or clean_env("APCA_API_SECRET_KEY")
    if not key or not secret:
        raise RuntimeError("Alpaca credentials are missing from the configured environment")
    allowed_emails = tuple(
        email.strip().lower()
        for email in os.getenv("ALLOWED_EMAILS", "").split(",")
        if email.strip()
    )
    return Settings(
        alpaca_key=key,
        alpaca_secret=secret,
        supabase_url=clean_env("SUPABASE_URL"),
        supabase_service_role_key=clean_env("SUPABASE_SERVICE_ROLE_KEY"),
        supabase_anon_key=clean_env("SUPABASE_ANON_KEY"),
        auth_required=(clean_env("AUTH_REQUIRED") or "false").lower() in {"1", "true", "yes"},
        weekly_ai_budget_usd=float(clean_env("WEEKLY_AI_BUDGET_USD") or "3.00"),
        allowed_emails=allowed_emails,
    )
