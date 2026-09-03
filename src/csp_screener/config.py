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
    universe: tuple[str, ...] = DEFAULT_UNIVERSE
    refresh_seconds: int = 900
    host: str = "127.0.0.1"
    port: int = 8080


def load_env_files() -> None:
    """Load repo-root and nested .env files without overriding existing values."""
    for path in (ROOT / ".env", ROOT / "csp-screener-capstone" / ".env"):
        if path.is_file():
            load_dotenv(path, override=False)
    shared_env = os.getenv("CSP_SHARED_ENV_FILE")
    if shared_env:
        shared = Path(shared_env).expanduser()
        if shared.exists():
            load_dotenv(shared, override=False)


def load_settings() -> Settings:
    """Load local and optional shared credentials without leaking them to clients."""
    load_env_files()
    key = os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID")
    secret = os.getenv("ALPACA_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY")
    if not key or not secret:
        raise RuntimeError("Alpaca credentials are missing from the configured environment")
    return Settings(alpaca_key=key, alpaca_secret=secret)
