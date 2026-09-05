from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolRoute:
    intent: str
    primary: tuple[str, ...]
    fallback: tuple[str, ...]
    reason: str


def route_research_tools(question: str) -> ToolRoute:
    """Choose read-only evidence tools deterministically before any LLM call."""
    text = question.strip().lower()
    if re.search(r"\b(my|the)\s+portfolio\b|\b(holdings|positions)\b", text):
        return ToolRoute(
            "portfolio_review", ("portfolio_store", "alpaca_market_mcp"),
            ("yahoo_finance_mcp", "tavily_search_mcp"),
            "Load every saved position first, refresh its market context, then research material risks.",
        )
    profile_only = (
        re.search(
            r"\b(configure|configuration|change|update|set|choose|recommend)\b.{0,50}"
            r"\b(profile|risk appetite|risk tolerance|preferences)\b",
            text,
        )
        or re.search(r"\bwhy\b.{0,30}\b(my )?profile\b", text)
    )
    if profile_only:
        return ToolRoute(
            "profile_advice", (), (),
            "Profile advice uses saved user context and deterministic bounds, not market-data tools.",
        )
    if re.search(r"\b(option|options|put|puts|csp|delta|dte|strike|premium|quote|price|support|resistance|volume|volatility|spread|spreads|bid ask)\b", text):
        return ToolRoute(
            "market_and_options", ("alpaca_market_mcp",),
            ("yahoo_finance_mcp",),
            "Alpaca is authoritative for live/historical market and option data.",
        )
    if re.search(r"\b(filing|10-q|10-k|8-k|earnings date|earnings calendar|fundamental)\b", text):
        return ToolRoute(
            "company_disclosure", ("yahoo_finance_mcp",),
            ("tavily_search_mcp",),
            "Yahoo supplies normalized filing and earnings metadata; Tavily can locate missing public evidence.",
        )
    if re.search(r"\b(latest|today|recent|news|regulation|lawsuit|competitor|competitors|industry|sector|macro|ai boom)\b", text):
        return ToolRoute(
            "current_web_research", ("alpaca_news_mcp", "tavily_search_mcp"),
            ("yahoo_finance_mcp",),
            "Use bounded market news plus web search for recent external developments.",
        )
    if re.search(r"\b(top|find|screen|candidate|candidates|stocks should|where should)\b", text):
        return ToolRoute(
            "candidate_discovery", ("alpaca_market_mcp",),
            ("yahoo_finance_mcp", "tavily_search_mcp"),
            "Screen authoritative market data first, then retrieve evidence only for eligible candidates.",
        )
    return ToolRoute(
        "company_research", ("yahoo_finance_mcp",),
        ("tavily_search_mcp",),
        "Start with the bounded company packet and use web search only when evidence is insufficient.",
    )


def evaluate_tool_routes(cases: list[dict[str, Any]]) -> dict[str, float]:
    """Score a versioned labeled routing dataset without calling external tools."""
    if not cases:
        raise ValueError("At least one routing case is required.")
    routes = [route_research_tools(str(case["question"])) for case in cases]
    profile_cases = [
        route for route, case in zip(routes, cases, strict=True)
        if case.get("intent") == "profile_advice"
    ]
    return {
        "intent_accuracy": round(sum(
            route.intent == case.get("intent")
            for route, case in zip(routes, cases, strict=True)
        ) / len(cases), 3),
        "primary_tool_exact_match": round(sum(
            list(route.primary) == case.get("primary", [])
            for route, case in zip(routes, cases, strict=True)
        ) / len(cases), 3),
        "profile_unnecessary_tool_rate": round(
            sum(bool(route.primary) for route in profile_cases) / len(profile_cases), 3
        ) if profile_cases else 0.0,
    }
