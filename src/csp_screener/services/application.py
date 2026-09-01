from __future__ import annotations

import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..config import Settings
from ..agents import ResearchAgent
from ..providers import AlpacaMarketDataProvider
from ..workflows import IterationOneConfig, IterationOneWorkflow


class ApplicationService:
    """Application boundary joining workflows, providers, cache, and scheduler."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        provider = AlpacaMarketDataProvider(
            settings.alpaca_key, settings.alpaca_secret
        )
        self.workflow = IterationOneWorkflow(
            provider, IterationOneConfig(universe=settings.universe)
        )
        self._screen_cache: dict[str, object] | None = None
        self._research_screen_cache: dict[str, object] | None = None
        self._cache_lock = threading.Lock()
        self._refresh_lock = threading.Lock()
        self._stop_refresh = threading.Event()
        self.agent = ResearchAgent(
            self.agent_market_context, self.discover_agent_candidates
        )

    def options(self, symbol: str) -> dict[str, object]:
        return self.workflow.options(symbol)

    def screen(self, *, force: bool = False, research: bool = False) -> dict[str, object]:
        with self._cache_lock:
            cached = self._research_screen_cache if research else self._screen_cache
            if cached is not None and not force:
                return {**cached, "cache_status": "hit"}

        # Cache hits never wait for a network refresh. Refresh misses are coalesced.
        with self._refresh_lock:
            with self._cache_lock:
                cached = self._research_screen_cache if research else self._screen_cache
                if cached is not None and not force:
                    return {**cached, "cache_status": "hit"}
            result = self.workflow.screen()
            if research:
                try:
                    result = {**result, **self.agent.classify_shortlist(result["candidates"])}
                except Exception as exc:
                    result = {
                        **result,
                        "research_status": "fallback",
                        "research_method": "Deterministic ranking preserved",
                        "research_warnings": [
                            f"Research classification unavailable: {type(exc).__name__}"
                        ],
                    }
            with self._cache_lock:
                if research:
                    self._research_screen_cache = result
                else:
                    self._screen_cache = result
                return {**result, "cache_status": "refreshed"}

    def research(self, symbol: str, question: str) -> dict[str, object]:
        return self.agent.ask(symbol, question)

    def start_background_refresh(self) -> None:
        def loop() -> None:
            while not self._stop_refresh.is_set():
                try:
                    self.screen(force=True, research=True)
                except Exception as exc:
                    print(f"[demo] scheduled refresh failed: {type(exc).__name__}")
                self._stop_refresh.wait(self.settings.refresh_seconds)

        threading.Thread(
            target=loop, name="iteration1-screen-refresh", daemon=True
        ).start()

    def stop_background_refresh(self) -> None:
        self._stop_refresh.set()

    def agent_market_context(self, symbol: str) -> dict[str, object]:
        options = self.workflow.options(symbol)
        ranking = next(
            (
                row for row in self.screen().get("candidates", [])
                if row.get("symbol") == symbol
            ),
            None,
        )
        contracts = []
        for row in options["contracts"]:
            midpoint = (float(row["bid"]) + float(row["ask"])) / 2
            contracts.append(
                {
                    "strategy": row["strategy"],
                    "type": row["type"],
                    "contract_symbol": row["symbol"],
                    "display_name": (
                        f"{symbol} · {options['expiration']} · "
                        f"${float(row['strike']):,.2f} {row['type'].lower()}"
                    ),
                    "strike": row["strike"],
                    "bid": row["bid"],
                    "ask": row["ask"],
                    "delta": row["delta"],
                    "implied_volatility": row["implied_volatility"],
                    "distance_pct": row["distance_pct"],
                    "cash_required": round(float(row["strike"]) * 100, 2)
                    if row["strategy"] == "Cash-secured put" else None,
                    "premium_yield_pct": round(
                        midpoint / float(row["strike"]) * 100, 2
                    ),
                }
            )
        return {
            "symbol": symbol,
            "spot": options["spot"],
            "expiration": options["expiration"],
            "stock_ranking": ranking,
            "contracts": contracts,
            "source": "Alpaca market data plus deterministic calculations",
        }

    @staticmethod
    def _budget(question: str) -> float | None:
        match = re.search(
            r"\$\s*([0-9][0-9,]*(?:\.\d+)?)\s*([kK]?)", question
        ) or re.search(
            r"(?:capital|budget)(?:\s+of|\s+is)?\s*\$?\s*"
            r"([0-9][0-9,]*(?:\.\d+)?)\s*([kK]?)",
            question,
            re.IGNORECASE,
        )
        if not match:
            return None
        value = float(match.group(1).replace(",", ""))
        return value * 1_000 if match.group(2).lower() == "k" else value

    def discover_agent_candidates(self, question: str) -> list[dict[str, object]]:
        budget = self._budget(question)
        candidates = list(self.screen().get("candidates", []))
        if budget is not None:
            candidates = [
                row for row in candidates if float(row["price"]) * 100 <= budget
            ]
        shortlist = [row["symbol"] for row in candidates[:5]]
        contexts: list[dict[str, object]] = []
        with ThreadPoolExecutor(max_workers=min(5, len(shortlist) or 1)) as pool:
            futures = {
                pool.submit(self.agent_market_context, symbol): symbol
                for symbol in shortlist
            }
            for future in as_completed(futures):
                try:
                    context = future.result()
                    context["discovery"] = {
                        "budget": budget,
                        "affordability_rule": (
                            "underlying price × 100 must not exceed budget"
                        ),
                    }
                    contexts.append(context)
                except Exception as exc:
                    print(
                        f"[demo] {futures[future]} discovery failed: "
                        f"{type(exc).__name__}"
                    )
        scores = {row["symbol"]: row["score"] for row in candidates}
        return sorted(
            contexts, key=lambda row: -scores.get(str(row["symbol"]), 0)
        )
