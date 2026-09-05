from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..config import Settings
from ..agents import ResearchAgent
from ..providers import AlpacaMarketDataProvider, SupabaseStateStore, YahooFinanceMCPClient
from ..workflows import IterationOneConfig, IterationOneWorkflow
from ..parsing import parse_budget, parse_requested_count
from ..profile_advisor import ProfileAdvisor


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
        self.state_store = (
            SupabaseStateStore(
                settings.supabase_url, settings.supabase_service_role_key
            )
            if settings.supabase_url and settings.supabase_service_role_key
            else None
        )
        try:
            self.agent: ResearchAgent | None = ResearchAgent(
                self.agent_market_context, self.discover_agent_candidates
            )
        except RuntimeError:
            # Deterministic screening remains usable when the optional model is
            # not configured. API responses expose the research fallback.
            self.agent = None
        try:
            self.profile_advisor: ProfileAdvisor | None = ProfileAdvisor()
        except RuntimeError:
            self.profile_advisor = None

    def recommend_profile(
        self, description: str, available_capital: float,
        current_profile: dict[str, object] | None = None,
    ) -> dict[str, object]:
        if self.profile_advisor is None:
            raise RuntimeError(
                "Profile Advisor is unavailable; configure OPENAI_API_KEY to enable it."
            )
        return self.profile_advisor.recommend(
            description, available_capital, current_profile
        )

    def options(
        self, symbol: str, *, profile: dict[str, object] | None = None
    ) -> dict[str, object]:
        result = self.workflow.options(symbol, profile)
        earnings_started = time.perf_counter()
        try:
            calendar = YahooFinanceMCPClient().next_earnings_date(symbol)
            earnings = calendar.get("next_earnings")
        except Exception:
            earnings = None
        latency = dict(result.get("latency_breakdown_ms", {}))
        latency["yahoo_mcp_earnings"] = round(
            (time.perf_counter() - earnings_started) * 1000
        )
        return {**result, "next_earnings": earnings, "latency_breakdown_ms": latency}

    def screen(
        self, *, force: bool = False, research: bool = False,
        profile: dict[str, object] | None = None,
    ) -> dict[str, object]:
        with self._cache_lock:
            cached = None if profile else (
                self._research_screen_cache if research else self._screen_cache
            )
            if cached is not None and not force:
                return {**cached, "cache_status": "hit"}

        if self.state_store is not None and not force and not profile:
            try:
                persisted = self.state_store.latest_screen(research)
                if persisted is not None:
                    with self._cache_lock:
                        if research:
                            self._research_screen_cache = persisted
                        else:
                            self._screen_cache = persisted
                    return {**persisted, "cache_status": "supabase"}
            except Exception as exc:
                print(f"[demo] Supabase cache read failed: {type(exc).__name__}")

        # Cache hits never wait for a network refresh. Refresh misses are coalesced.
        with self._refresh_lock:
            with self._cache_lock:
                cached = None if profile else (
                    self._research_screen_cache if research else self._screen_cache
                )
                if cached is not None and not force:
                    return {**cached, "cache_status": "hit"}
            result = self.workflow.screen(profile)
            if research:
                try:
                    if self.agent is None:
                        raise RuntimeError("Research model is not configured")
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
                if not profile and research:
                    self._research_screen_cache = result
                elif not profile:
                    self._screen_cache = result
            if self.state_store is not None and not profile:
                try:
                    self.state_store.save_screen(result, research)
                except Exception as exc:
                    print(f"[demo] Supabase cache write failed: {type(exc).__name__}")
            return {**result, "cache_status": "refreshed"}

    def research(
        self, symbol: str, question: str, *, profile: dict[str, object] | None = None,
        portfolio_positions: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        if self.agent is None:
            raise RuntimeError(
                "Research agent is unavailable; configure OPENAI_API_KEY to enable it."
            )
        response = self.agent.ask(
            symbol, question, profile=profile,
            portfolio_positions=portfolio_positions,
        )
        if self.state_store is not None:
            try:
                self.state_store.save_research(symbol, question, response)
            except Exception as exc:
                print(f"[demo] Supabase research write failed: {type(exc).__name__}")
        return response

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

    def agent_market_context(
        self, symbol: str, profile: dict[str, object] | None = None
    ) -> dict[str, object]:
        try:
            options = self.workflow.options(
                symbol,
                profile,
                enforce_capital=False,
                require_calls=False,
            )
        except ValueError as exc:
            # Keep deterministic rejection evidence available to the research graph.
            return {
                "symbol": symbol,
                "spot": None,
                "expiration": None,
                "stock_ranking": None,
                "contracts": [],
                "eligibility": "excluded",
                "rejection_reason": str(exc),
                "source": "Alpaca market data plus deterministic profile rules",
                "profile": profile or {},
            }
        ranking = next(
            (
                row for row in self.screen(profile=profile).get("candidates", [])
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
            "eligibility": "eligible",
            "rejection_reason": None,
            "source": "Alpaca market data plus deterministic calculations",
            "profile": profile or {},
        }

    def discover_agent_candidates(
        self, question: str, profile: dict[str, object] | None = None
    ) -> list[dict[str, object]]:
        explicit_budget = parse_budget(question)
        profile_budget = float(profile.get("available_capital", 0)) if profile else None
        allocation = float(profile.get("max_allocation_pct", 100)) if profile else 100
        budget = explicit_budget or (
            profile_budget * allocation / 100 if profile_budget else None
        )
        candidates = list(self.screen(profile=profile).get("candidates", []))
        requested_count = parse_requested_count(question)
        # Load a wider deterministic pool first. CSP affordability depends on the
        # eligible put strike, not on buying 100 shares at the current stock price.
        shortlist = [row["symbol"] for row in candidates[:10]]
        contexts: list[dict[str, object]] = []
        with ThreadPoolExecutor(max_workers=min(5, len(shortlist) or 1)) as pool:
            futures = {
                pool.submit(self.agent_market_context, symbol, profile): symbol
                for symbol in shortlist
            }
            for future in as_completed(futures):
                try:
                    context = future.result()
                    context["discovery"] = {
                        "budget": budget,
                        "requested_count": requested_count,
                        "affordability_rule": "eligible CSP strike × 100 must not exceed budget",
                    }
                    puts = [
                        row for row in context.get("contracts", [])
                        if row.get("strategy") == "Cash-secured put"
                    ]
                    minimum_cash = min(
                        (float(row["cash_required"]) for row in puts), default=None
                    )
                    if budget is None or (
                        minimum_cash is not None and minimum_cash <= budget
                    ):
                        context["discovery"]["minimum_cash_required"] = minimum_cash
                        contexts.append(context)
                except Exception as exc:
                    print(
                        f"[demo] {futures[future]} discovery failed: "
                        f"{type(exc).__name__}"
                    )
        scores = {row["symbol"]: row["score"] for row in candidates}
        return sorted(
            contexts, key=lambda row: -scores.get(str(row["symbol"]), 0)
        )[:requested_count]
