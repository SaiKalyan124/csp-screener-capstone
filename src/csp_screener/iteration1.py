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
        self._option_cache: dict[tuple[object, ...], dict[str, object]] = {}
        self._option_cache_lock = threading.Lock()

    def screen(self, profile: dict[str, object] | None = None) -> dict[str, object]:
        started = time.perf_counter()
        now = datetime.now(timezone.utc)
        bars_started = time.perf_counter()
        bars = self.provider.daily_bars(
            list(self.config.universe), now - timedelta(days=120)
        )
        bars_ms = round((time.perf_counter() - bars_started) * 1000)
        ranking_started = time.perf_counter()
        stock_candidates = rank_stock_candidates(
            bars, limit=min(len(self.config.universe), self.config.stock_pool_size)
        )
        ranking_ms = round((time.perf_counter() - ranking_started) * 1000)
        with self._option_cache_lock:
            self._option_cache = {}
        eligible_by_symbol: dict[str, dict[str, object]] = {}
        rejected_options: dict[str, str] = {}
        option_started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=min(5, len(stock_candidates) or 1)) as pool:
            futures = {
                pool.submit(
                    self.options, candidate.symbol, profile,
                    enforce_capital=False, require_calls=False,
                ): candidate.symbol
                for candidate in stock_candidates
            }
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    eligible_by_symbol[symbol] = future.result()
                except Exception as exc:
                    rejected_options[symbol] = str(exc)
        option_screen_ms = round((time.perf_counter() - option_started) * 1000)

        candidates: list[dict[str, object]] = []
        for candidate in stock_candidates:
            option_result = eligible_by_symbol.get(candidate.symbol)
            if option_result is None:
                continue
            contracts = list(option_result["contracts"])
            puts = [row for row in contracts if row["strategy"] == "Cash-secured put"]
            calls = [row for row in contracts if row["strategy"] == "Covered call"]
            profile_rules = profile or {}
            capital = float(profile_rules.get("available_capital", 0) or 0)
            allocation = float(profile_rules.get("max_allocation_pct", 100) or 100)
            position_limit = capital * allocation / 100 if capital else None
            minimum_collateral = min(
                (float(row["strike"]) * 100 for row in puts), default=None
            )
            capital_fit = (
                "not_configured" if position_limit is None
                else "fits" if minimum_collateral is not None and minimum_collateral <= position_limit
                else "exceeds_limit"
            )
            candidates.append({
                **candidate.to_dict(),
                "option_eligible": True,
                "eligible_put_count": len(puts),
                "eligible_call_count": len(calls),
                "best_csp_score": max(row["rank_score"] for row in puts),
                "option_expiration": option_result["expiration"],
                "minimum_csp_collateral": minimum_collateral,
                "profile_position_limit": position_limit,
                "capital_fit": capital_fit,
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
            "latency_breakdown_ms": {
                "alpaca_stock_bars": bars_ms,
                "deterministic_stock_ranking": ranking_ms,
                "parallel_option_screen": option_screen_ms,
            },
            "method": (
                "Stock eligibility and score, followed by required validation of "
                "five CSPs under the configured contract rules; covered calls and "
                "profile capital fit are reported as context"
            ),
            "candidates": candidates,
        }

    def options(
        self, symbol: str, profile: dict[str, object] | None = None, *,
        enforce_capital: bool = True, require_calls: bool = True,
    ) -> dict[str, object]:
        symbol = symbol.strip().upper()
        profile = profile or {}
        dte_min = int(profile.get("dte_min", self.config.dte_min))
        dte_max = int(profile.get("dte_max", self.config.dte_max))
        min_delta = float(profile.get("delta_min", self.config.min_abs_delta))
        max_delta = float(profile.get("delta_max", self.config.max_abs_delta))
        spread = float(profile.get("max_spread_pct", self.config.max_option_spread_pct))
        capital = float(profile.get("available_capital", 0) or 0)
        allocation = float(profile.get("max_allocation_pct", 100) or 100)
        max_put_collateral = (
            capital * allocation / 100 if capital and enforce_capital else None
        )
        target_delta = round((min_delta + max_delta) / 2, 4)
        cache_key = (
            symbol, dte_min, dte_max, min_delta, max_delta, spread,
            max_put_collateral, require_calls,
        )
        if not profile:
            with self._option_cache_lock:
                cached = self._option_cache.get(cache_key)
            if cached is not None:
                return cached
        started = time.perf_counter()
        trade_started = time.perf_counter()
        trade = self.provider.latest_trade(symbol)
        trade_ms = round((time.perf_counter() - trade_started) * 1000)
        if trade is None:
            raise ValueError(f"No latest trade found for {symbol}")
        spot = float(trade.price)
        today = date.today()
        chain_started = time.perf_counter()
        snapshots = self.provider.option_chain(
            symbol,
            expiration_gte=today + timedelta(days=dte_min),
            expiration_lte=today + timedelta(days=dte_max),
            strike_gte=round(spot * 0.75, 2),
            strike_lte=round(spot * 1.25, 2),
        )
        chain_ms = round((time.perf_counter() - chain_started) * 1000)
        calculation_started = time.perf_counter()
        expiry, rows = select_csp_and_covered_calls(
            snapshots,
            spot,
            count=self.config.contract_count,
            min_bid=self.config.min_option_bid,
            max_spread_pct=spread,
            min_abs_delta=min_delta,
            max_abs_delta=max_delta,
            target_abs_delta=target_delta,
            max_put_collateral=max_put_collateral,
            require_calls=require_calls,
        )
        calculation_ms = round((time.perf_counter() - calculation_started) * 1000)
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
            "latency_breakdown_ms": {
                "alpaca_latest_trade": trade_ms,
                "alpaca_option_chain": chain_ms,
                "deterministic_contract_ranking": calculation_ms,
            },
            "source_count": len(snapshots),
            "selection_method": (
                "Eligible contracts ranked by delta fit (50%), spread quality "
                "(30%), and bid liquidity (20%)"
            ),
            "eligibility_rules": {
                "dte": [dte_min, dte_max],
                "minimum_bid": self.config.min_option_bid,
                "maximum_spread_pct": spread,
                "absolute_delta": [
                    min_delta,
                    max_delta,
                ],
                "maximum_put_collateral": max_put_collateral,
            },
            "profile_applied": bool(profile),
        }
        if not profile:
            with self._option_cache_lock:
                self._option_cache[cache_key] = result
        return result
