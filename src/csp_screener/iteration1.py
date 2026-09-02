from __future__ import annotations

import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    min_option_bid: float = 0.10
    max_option_spread_pct: float = 20.0
    min_abs_delta: float = 0.15
    max_abs_delta: float = 0.40
    target_abs_delta: float = 0.25
    stock_pool_size: int = 30


class IterationOneWorkflow:
    """Deterministic Iteration 1 orchestration; no LLM or agent routing."""

    def __init__(self, provider: MarketDataProvider, config: IterationOneConfig):
        self.provider = provider
        self.config = config
        self._option_cache: dict[str, dict[str, object]] = {}
        self._option_cache_lock = threading.Lock()

    def screen(self) -> dict[str, object]:
        started = time.perf_counter()
        now = datetime.now(timezone.utc)
        bars = self.provider.daily_bars(
            list(self.config.universe), now - timedelta(days=120)
        )
        stock_candidates = rank_stock_candidates(
            bars, limit=min(len(self.config.universe), self.config.stock_pool_size)
        )
        with self._option_cache_lock:
            self._option_cache = {}
        eligible_by_symbol: dict[str, dict[str, object]] = {}
        rejected_options: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=min(5, len(stock_candidates) or 1)) as pool:
            futures = {
                pool.submit(self.options, candidate.symbol): candidate.symbol
                for candidate in stock_candidates
            }
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    eligible_by_symbol[symbol] = future.result()
                except Exception as exc:
                    rejected_options[symbol] = str(exc)

        candidates: list[dict[str, object]] = []
        for candidate in stock_candidates:
            option_result = eligible_by_symbol.get(candidate.symbol)
            if option_result is None:
                continue
            contracts = list(option_result["contracts"])
            puts = [row for row in contracts if row["strategy"] == "Cash-secured put"]
            calls = [row for row in contracts if row["strategy"] == "Covered call"]
            candidates.append({
                **candidate.to_dict(),
                "option_eligible": True,
                "eligible_put_count": len(puts),
                "eligible_call_count": len(calls),
                "best_csp_score": max(row["rank_score"] for row in puts),
                "option_expiration": option_result["expiration"],
            })
            if len(candidates) == 10:
                break
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
            "stock_qualified_count": len(stock_candidates),
            "qualified_count": len(candidates),
            "option_rejected_count": len(rejected_options),
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "method": (
                "Stock eligibility and score, followed by required validation of "
                "five CSPs and five covered calls under the configured contract rules"
            ),
            "candidates": candidates,
        }

    def options(self, symbol: str) -> dict[str, object]:
        symbol = symbol.strip().upper()
        with self._option_cache_lock:
            cached = self._option_cache.get(symbol)
        if cached is not None:
            return cached
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
            snapshots,
            spot,
            count=self.config.contract_count,
            min_bid=self.config.min_option_bid,
            max_spread_pct=self.config.max_option_spread_pct,
            min_abs_delta=self.config.min_abs_delta,
            max_abs_delta=self.config.max_abs_delta,
            target_abs_delta=self.config.target_abs_delta,
        )
        result: dict[str, object] = {
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
            "selection_method": (
                "Eligible contracts ranked by delta fit (50%), spread quality "
                "(30%), and bid liquidity (20%)"
            ),
            "eligibility_rules": {
                "dte": [self.config.dte_min, self.config.dte_max],
                "minimum_bid": self.config.min_option_bid,
                "maximum_spread_pct": self.config.max_option_spread_pct,
                "absolute_delta": [
                    self.config.min_abs_delta,
                    self.config.max_abs_delta,
                ],
            },
        }
        with self._option_cache_lock:
            self._option_cache[symbol] = result
        return result
