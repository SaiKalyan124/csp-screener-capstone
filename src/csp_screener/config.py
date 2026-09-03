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
    key = os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID")
    secret = os.getenv("ALPACA_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY")
    if not key or not secret:
        raise RuntimeError("Alpaca credentials are missing from the configured environment")
    return Settings(
        alpaca_key=key,
        alpaca_secret=secret,
        supabase_url=os.getenv("SUPABASE_URL") or None,
        supabase_service_role_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY") or None,
        supabase_anon_key=os.getenv("SUPABASE_ANON_KEY") or None,
        auth_required=os.getenv("AUTH_REQUIRED", "false").lower() in {"1", "true", "yes"},
    )
