from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Protocol

from .screen import rank_stock_candidates, select_csp_and_covered_calls


class MarketDataProvider(Protocol):
    def latest_trade(self, symbol: str) -> Any: ...

    def daily_bars(self, symbols: list[str], start: datetime) -> dict[str, Iterable[Any]]: ...

    def option_chain(
        self,
        symbol: str,
        *,
        expiration_gte: date,
        expiration_lte: date,
        strike_gte: float,
        strike_lte: float,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class IterationOneConfig:
    universe: tuple[str, ...]
    dte_min: int = 20
    dte_max: int = 35
    contract_count: int = 5


class IterationOneWorkflow:
    """Deterministic Iteration 1 orchestration; no LLM or agent routing."""

    def __init__(self, provider: MarketDataProvider, config: IterationOneConfig):
        self.provider = provider
        self.config = config

    def screen(self) -> dict[str, object]:
        started = time.perf_counter()
        now = datetime.now(timezone.utc)
        bars = self.provider.daily_bars(
            list(self.config.universe), now - timedelta(days=120)
        )
        candidates = rank_stock_candidates(bars, limit=10)
        data_as_of = max(
            (
                getattr(bar, "timestamp", None)
                for rows in bars.values()
                for bar in rows
                if getattr(bar, "timestamp", None) is not None
            ),
            default=None,
        )
        return {
            "iteration": 1,
            "workflow": "python-deterministic",
            "generated_at": now.isoformat(),
            "data_as_of": data_as_of.isoformat() if data_as_of else None,
            "universe_count": len(self.config.universe),
            "qualified_count": len(candidates),
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "method": "40% liquidity · 35% 3-month momentum · 25% realized volatility",
            "candidates": [candidate.to_dict() for candidate in candidates],
        }

    def options(self, symbol: str) -> dict[str, object]:
        started = time.perf_counter()
        trade = self.provider.latest_trade(symbol)
        if trade is None:
            raise ValueError(f"No latest trade found for {symbol}")
        spot = float(trade.price)
        today = date.today()
        snapshots = self.provider.option_chain(
            symbol,
            expiration_gte=today + timedelta(days=self.config.dte_min),
            expiration_lte=today + timedelta(days=self.config.dte_max),
            strike_gte=round(spot * 0.75, 2),
            strike_lte=round(spot * 1.25, 2),
        )
        expiry, rows = select_csp_and_covered_calls(
            snapshots, spot, count=self.config.contract_count
        )
        return {
            "iteration": 1,
            "workflow": "python-deterministic",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "spot": spot,
            "trade_timestamp": trade.timestamp.isoformat(),
            "expiration": expiry.isoformat(),
            "contracts": rows,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "source_count": len(snapshots),
        }
