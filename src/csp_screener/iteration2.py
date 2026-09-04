from __future__ import annotations

import os
import re
from datetime import datetime
from time import perf_counter
from typing import Annotated, Any, Callable, TypedDict

from pydantic import BaseModel, Field

from .course_e2e import _normalize_filings
from .observability import TracingStatus, setup_tracing
from .providers import YahooFinanceMCPClient
from .parsing import parse_budget, parse_requested_count
from .tool_routing import route_research_tools


class ResearchState(TypedDict, total=False):
    symbol: str
    symbols: list[str]
    question: str
    evidence: list[dict[str, Any]]
    market_context: list[dict[str, Any]]
    answer: str
    risk_level: str
    citations: list[dict[str, str]]
    warnings: list[str]
    discovery_requested: bool
    budget: float | None
    requested_count: int
    intent: str
    research_summary: dict[str, Any]
    selected_symbol: str | None
    display_symbols: list[str]
    ui_candidates: list[dict[str, Any]]
    mandate: dict[str, Any]
    data_quality: dict[str, Any]
    eligibility_ledger: list[dict[str, Any]]
    portfolio_fit: dict[str, dict[str, Any]]
    scenario_matrix: dict[str, dict[str, Any]]
    research_dossier: dict[str, Any]
    risk_decision: dict[str, Any]
    audit_record: dict[str, Any]
    profile: dict[str, Any]
    tool_route: dict[str, Any]
    latency_breakdown_ms: dict[str, float]


class ShortlistState(TypedDict, total=False):
    candidates: list[dict[str, Any]]
    evidence_by_symbol: dict[str, list[dict[str, Any]]]
    raw_classifications: list[dict[str, Any]]
    warnings: list[str]
    output: dict[str, Any]
    evidence_summary: dict[str, Any]


def _prepare_eligible_shortlist(state: ShortlistState) -> dict[str, Any]:
    """Keep deterministic eligibility authoritative before research begins."""
    eligible = [
        row for row in state.get("candidates", [])
        if row.get("option_eligible") is True
        and row.get("eligible_put_count", 0) >= 5
    ][:10]
    return {"candidates": eligible, "warnings": list(state.get("warnings", []))}


def _assess_shortlist_evidence(state: ShortlistState) -> dict[str, Any]:
    rows = state.get("evidence_by_symbol", {})
    return {"evidence_summary": {
        "symbols_requested": len(state.get("candidates", [])),
        "symbols_with_evidence": sum(bool(items) for items in rows.values()),
        "documents_retrieved": sum(len(items) for items in rows.values()),
    }}


class ResearchAnswer(BaseModel):
    bullet_points: list[
        Annotated[str, Field(min_length=1, max_length=240)]
    ] = Field(
        min_length=1,
        max_length=10,
        description=(
            "One to ten concise, non-redundant bullets grounded only in supplied evidence"
        ),
    )
    risk_level: str = Field(description="low, medium, high, or unknown")
    cited_urls: list[str] = Field(description="Only URLs present in supplied evidence")
    selected_symbol: str | None = Field(
        description="Best ticker to display from the supplied market context, or null"
    )
    display_symbols: list[str] = Field(
        description="Tickers discussed as candidates, in the same order as the answer"
    )


class CandidateClassification(BaseModel):
    symbol: str
    classification: str = Field(description="favorable, watch, avoid, or insufficient_evidence")
    reason: str = Field(description="One evidence-grounded sentence; no price prediction")
    cited_urls: list[str] = Field(default_factory=list)


class ShortlistClassification(BaseModel):
    candidates: list[CandidateClassification]


def _candidate_evidence(symbol: str) -> list[dict[str, Any]]:
    """Collect a small, bounded evidence packet for dashboard classification."""
    packet = YahooFinanceMCPClient().company_evidence(
        symbol, filing_limit=2, news_limit=3
    )
    return [*(packet.get("filings") or []), *(packet.get("news") or [])][:5]


def _retrieve_shortlist_evidence(state: ShortlistState) -> dict[str, Any]:
    evidence_by_symbol: dict[str, list[dict[str, Any]]] = {}
    warnings = list(state.get("warnings", []))
    bounded = state["candidates"][:10]
    symbols = [row["symbol"] for row in bounded]
    try:
        result = YahooFinanceMCPClient().company_evidence_batch(
            symbols, filing_limit=2, news_limit=3
        )
        for symbol in symbols:
            packet = (result.get("evidence") or {}).get(symbol, {})
            evidence_by_symbol[symbol] = [
                *(packet.get("filings") or []), *(packet.get("news") or [])
            ][:5]
        for symbol, error in (result.get("errors") or {}).items():
            warnings.append(f"{symbol} research unavailable: {error}")
    except Exception as exc:
        warnings.append(f"Yahoo MCP unavailable: {type(exc).__name__}")
        evidence_by_symbol = {symbol: [] for symbol in symbols}
    return {"evidence_by_symbol": evidence_by_symbol, "warnings": warnings}


def _classify_shortlist_with_llm(state: ShortlistState) -> dict[str, Any]:
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_openai import ChatOpenAI

    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            "Classify each supplied, deterministically eligible CSP stock as favorable, "
            "watch, avoid, or insufficient_evidence. Consider only material event and "
            "company risk visible in the supplied headlines and filing metadata. Do not "
            "predict returns, change numerical scores, or infer filing contents. Use "
            "insufficient_evidence when support is weak. Return one result per symbol and "
            "only cite supplied URLs.",
        ),
        ("human", "Deterministic shortlist: {candidates}\nEvidence by symbol: {evidence}"),
    ])
    model = ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", "gpt-5-mini"), temperature=0
    ).with_structured_output(ShortlistClassification)
    result = (prompt | model).invoke({
        "candidates": state["candidates"][:10],
        "evidence": state["evidence_by_symbol"],
    })
    return {
        "raw_classifications": [item.model_dump() for item in result.candidates]
    }


def _validate_shortlist_classification(state: ShortlistState) -> dict[str, Any]:
    bounded = state["candidates"][:10]
    allowed_symbols = {row["symbol"] for row in bounded}
    original_scores = {row["symbol"]: row["score"] for row in bounded}
    allowed_urls = {
        symbol: {str(item.get("url")) for item in rows if item.get("url")}
        for symbol, rows in state["evidence_by_symbol"].items()
    }
    accepted: dict[str, dict[str, Any]] = {}
    labels = {"favorable", "watch", "avoid", "insufficient_evidence"}
    returned_citations = 0
    accepted_citations = 0
    for item in state["raw_classifications"]:
        symbol = str(item.get("symbol", ""))
        classification = str(item.get("classification", ""))
        citations = [str(url) for url in item.get("cited_urls", [])]
        returned_citations += len(citations)
        if symbol not in allowed_symbols or classification not in labels:
            continue
        valid_citations = [
            url for url in citations if url in allowed_urls.get(symbol, set())
        ]
        accepted_citations += len(valid_citations)
        accepted[symbol] = {
            "classification": classification,
            "research_reason": str(item.get("reason", "")),
            "research_citations": valid_citations,
        }

    enriched = []
    for row in bounded:
        research = accepted.get(row["symbol"], {
            "classification": "insufficient_evidence",
            "research_reason": "No supported research classification was returned.",
            "research_citations": [],
        })
        enriched.append({**row, **research})
    order = {"favorable": 0, "watch": 1, "insufficient_evidence": 2, "avoid": 3}
    enriched = sorted(
        enriched, key=lambda row: (order[row["classification"]], -row["score"])
    )
    evaluated_symbols = {row["symbol"] for row in enriched}
    evaluations = {
        "classification_coverage": round(len(accepted) / len(bounded), 3)
        if bounded else 1.0,
        "eligible_symbol_precision": round(
            len(evaluated_symbols & allowed_symbols) / len(evaluated_symbols), 3
        ) if evaluated_symbols else 1.0,
        "citation_precision": round(accepted_citations / returned_citations, 3)
        if returned_citations else 1.0,
        "score_integrity": 1.0 if all(
            row["score"] == original_scores[row["symbol"]] for row in enriched
        ) else 0.0,
        "contract_eligibility_integrity": 1.0 if all(
            row.get("option_eligible") is True
            and row.get("eligible_put_count", 0) >= 5
            for row in enriched
        ) else 0.0,
    }
    return {"output": {
        "candidates": enriched,
        "research_status": "complete",
        "research_warnings": state["warnings"],
        "research_method": (
            "LangGraph: parallel evidence retrieval → one LangChain structured "
            "classification call → deterministic validation"
        ),
        "evaluation_scores": evaluations,
    }}


def build_shortlist_graph():
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(ShortlistState)
    graph.add_node("prepare_eligible_shortlist", _prepare_eligible_shortlist)
    graph.add_node("retrieve_yahoo_mcp_evidence", _retrieve_shortlist_evidence)
    graph.add_node("assess_event_and_company_evidence", _assess_shortlist_evidence)
    graph.add_node("classify_shortlist_with_llm", _classify_shortlist_with_llm)
    graph.add_node("validate_scores_citations_and_eligibility", _validate_shortlist_classification)
    graph.add_edge(START, "prepare_eligible_shortlist")
    graph.add_edge("prepare_eligible_shortlist", "retrieve_yahoo_mcp_evidence")
    graph.add_edge("retrieve_yahoo_mcp_evidence", "assess_event_and_company_evidence")
    graph.add_edge("assess_event_and_company_evidence", "classify_shortlist_with_llm")
    graph.add_edge("classify_shortlist_with_llm", "validate_scores_citations_and_eligibility")
    graph.add_edge("validate_scores_citations_and_eligibility", END)
    return graph.compile()


def _parse_question_and_profile(state: ResearchState) -> dict[str, Any]:
    symbol = state.get("symbol", "").strip().upper()
    question = state.get("question", "").strip()
    if not re.fullmatch(r"[A-Z][A-Z.\-]{0,9}", symbol):
        raise ValueError("Enter a valid ticker.")
    if not question or len(question) > 600:
        raise ValueError("Ask a research question between 1 and 600 characters.")
    discovery = ResearchAgent._needs_discovery(question)
    symbols = [] if discovery else ResearchAgent._symbols(symbol, question)
    profile = state.get("profile", {})
    explicit_budget = parse_budget(question)
    available_capital = float(profile.get("available_capital", 0) or 0)
    allocation_pct = float(profile.get("max_allocation_pct", 100) or 100)
    profile_position_limit = (
        available_capital * allocation_pct / 100 if available_capital else None
    )
    budget = explicit_budget or profile_position_limit
    requested_count = parse_requested_count(question)
    tool_route = route_research_tools(question)
    return {
        "symbol": symbol,
        "question": question,
        "symbols": symbols,
        "discovery_requested": discovery,
        "intent": "candidate_discovery" if discovery else "ticker_research",
        "budget": budget,
        "requested_count": requested_count,
        "tool_route": {
            "intent": tool_route.intent,
            "primary": list(tool_route.primary),
            "fallback": list(tool_route.fallback),
            "reason": tool_route.reason,
        },
        "mandate": {
            "budget": budget,
            "requested_count": requested_count,
            "strategy": "cash_secured_put",
            "risk_tolerance": next(
                (risk for risk in ("low", "medium", "high") if f"{risk} risk" in question.lower()),
                str(profile.get("risk_level") or "unspecified"),
            ),
            "profile_position_limit": profile_position_limit,
            "profile_mode": profile.get("mode"),
            "dte_range": [profile.get("dte_min"), profile.get("dte_max")],
            "delta_range": [profile.get("delta_min"), profile.get("delta_max")],
            "avoid_earnings_preference": profile.get("avoid_earnings"),
            "willing_to_own_underlying": "unknown",
            "decision_scope": "research_only",
        },
    }


def _route_research_intent(state: ResearchState) -> str:
    return "deterministic_universe_screen" if state.get("discovery_requested") else "load_explicit_ticker_market_data"


def _market_data_quality_gate(state: ResearchState) -> dict[str, Any]:
    missing: list[str] = []
    contexts = state.get("market_context", [])
    if not contexts:
        missing.append("market_context")
    for context in contexts:
        if context.get("spot") is None:
            missing.append(f"{context.get('symbol')}:spot")
        if not context.get("contracts"):
            missing.append(f"{context.get('symbol')}:contracts")
    return {"data_quality": {
        "status": "usable" if not missing else "insufficient",
        "missing_fields": missing,
        "symbols_checked": len(contexts),
        "source": "Alpaca market data",
    }}


def _deterministic_contract_eligibility(state: ResearchState) -> dict[str, Any]:
    ledger: list[dict[str, Any]] = []
    for context in state.get("market_context", []):
        for contract in context.get("contracts", []):
            reasons: list[str] = []
            bid = float(contract.get("bid") or 0)
            ask = float(contract.get("ask") or 0)
            if bid <= 0:
                reasons.append("non_positive_bid")
            if ask < bid:
                reasons.append("crossed_quote")
            if contract.get("delta") is None:
                reasons.append("missing_delta")
            ledger.append({
                "symbol": context.get("symbol"),
                "contract": contract.get("contract_symbol"),
                "eligible": not reasons,
                "reason_codes": reasons,
            })
    return {"eligibility_ledger": ledger}


def _portfolio_fit_and_stress(state: ResearchState) -> dict[str, Any]:
    """Calculate collateral fit and downside scenarios without LLM judgment."""
    contexts = state.get("market_context", [])
    budget = state.get("budget")
    portfolio_fit: dict[str, dict[str, Any]] = {}
    scenarios: dict[str, dict[str, Any]] = {}
    for context in contexts:
        symbol = str(context.get("symbol"))
        puts = [row for row in context.get("contracts", []) if row.get("strategy") == "Cash-secured put"]
        cash_values = [float(row.get("cash_required") or float("inf")) for row in puts]
        minimum_cash = min(cash_values, default=None)
        portfolio_fit[symbol] = {
            "minimum_cash_required": minimum_cash,
            "affordable": budget is None or (minimum_cash is not None and minimum_cash <= budget),
            "budget_utilization_pct": round(minimum_cash / budget * 100, 2) if budget and minimum_cash else None,
        }
        if puts:
            selected = min(puts, key=lambda row: abs(abs(float(row.get("delta") or 0)) - 0.25))
            strike = float(selected["strike"])
            premium = (float(selected["bid"]) + float(selected["ask"])) / 2
            effective_entry = strike - premium
            scenarios[symbol] = {
                "contract": selected.get("display_name"),
                "effective_entry": round(effective_entry, 2),
                "max_loss_if_stock_zero": round(effective_entry * 100, 2),
                "loss_at_10pct_below_strike": round(max(effective_entry - strike * 0.9, 0) * 100, 2),
                "loss_at_20pct_below_strike": round(max(effective_entry - strike * 0.8, 0) * 100, 2),
                "loss_at_35pct_below_strike": round(max(effective_entry - strike * 0.65, 0) * 100, 2),
            }
    return {"research_summary": {
        "intent": state.get("intent"),
        "budget": budget,
        "market_symbols": [row.get("symbol") for row in contexts],
        "affordable_symbol_count": sum(row["affordable"] for row in portfolio_fit.values()),
        "eligibility_authority": "deterministic",
    }, "portfolio_fit": portfolio_fit, "scenario_matrix": scenarios}


def _assess_research_evidence(state: ResearchState) -> dict[str, Any]:
    summary = dict(state.get("research_summary", {}))
    summary.update({
        "evidence_documents": len(state.get("evidence", [])),
        "evidence_urls": [row.get("url") for row in state.get("evidence", []) if row.get("url")],
    })
    evidence = state.get("evidence", [])
    source_types = sorted({str(row.get("type") or "Unknown") for row in evidence})
    dossier = {
        "facts": evidence,
        "source_types": source_types,
        "coverage": "sufficient" if len(evidence) >= 2 else "limited",
        "analyst_instructions": {
            "thesis": "State only evidence-supported reasons the underlying may be acceptable to own.",
            "counter_thesis": "Actively identify disconfirming evidence, downside catalysts, and missing facts.",
            "uncertainty": "Do not equate missing adverse evidence with low risk.",
        },
    }
    return {"research_summary": summary, "research_dossier": dossier}


def _independent_risk_gate(state: ResearchState) -> dict[str, Any]:
    reasons: list[str] = []
    if state.get("data_quality", {}).get("status") != "usable":
        reasons.append("insufficient_market_data")
    if not any(row.get("eligible") for row in state.get("eligibility_ledger", [])):
        reasons.append("no_eligible_contracts")
    if state.get("budget") is not None and not any(
        row.get("affordable") for row in state.get("portfolio_fit", {}).values()
    ):
        reasons.append("insufficient_cash_collateral")
    if state.get("research_dossier", {}).get("coverage") == "limited":
        reasons.append("limited_research_evidence")
    hard_vetoes = {"insufficient_market_data", "no_eligible_contracts", "insufficient_cash_collateral"}
    return {"risk_decision": {
        "status": "veto" if hard_vetoes.intersection(reasons) else ("watch" if reasons else "pass"),
        "reason_codes": reasons,
        "llm_can_override": False,
    }}


def _record_decision_and_evals(state: ResearchState) -> dict[str, Any]:
    citations = state.get("citations", [])
    allowed = {str(row.get("url")) for row in state.get("evidence", []) if row.get("url")}
    return {"audit_record": {
        "intent": state.get("intent"),
        "route": "discovery" if state.get("discovery_requested") else "explicit_ticker",
        "symbols": state.get("symbols", []),
        "eligible_contract_count": sum(bool(row.get("eligible")) for row in state.get("eligibility_ledger", [])),
        "risk_status": state.get("risk_decision", {}).get("status"),
        "risk_reason_codes": state.get("risk_decision", {}).get("reason_codes", []),
        "citation_precision": round(sum(row.get("url") in allowed for row in citations) / len(citations), 3) if citations else 1.0,
        "format_compliance": 1 <= len(state.get("answer", "").splitlines()) <= 10,
        "ranking_authority": "deterministic",
        "tool_route": state.get("tool_route", {}),
        "latency_breakdown_ms": state.get("latency_breakdown_ms", {}),
    }}


def _validate_grounding_and_citations(state: ResearchState) -> dict[str, Any]:
    allowed_urls = {str(row.get("url")) for row in state.get("evidence", []) if row.get("url")}
    citations = [row for row in state.get("citations", []) if row.get("url") in allowed_urls]
    lines = [line for line in state.get("answer", "").splitlines() if line.strip()]
    if not 1 <= len(lines) <= 10 or any(not line.startswith("- ") for line in lines):
        raise ValueError("Research response must contain between one and ten bullet points.")
    context_symbols = {str(row.get("symbol")) for row in state.get("market_context", [])}
    display = [symbol for symbol in state.get("display_symbols", []) if symbol in context_symbols]
    if state.get("discovery_requested"):
        requested_count = int(state.get("requested_count", 3))
        # Keep the deterministic shortlist authoritative for the screener cards.
        display = [
            str(row["symbol"]) for row in state.get("market_context", [])
            if row.get("symbol") in context_symbols
        ][:requested_count]
    selected = state.get("selected_symbol")
    return {
        "citations": citations,
        "display_symbols": display,
        "selected_symbol": selected if selected in context_symbols else None,
    }


def _prepare_screener_cards(state: ResearchState) -> dict[str, Any]:
    contexts = {row["symbol"]: row for row in state.get("market_context", [])}
    answer_symbols = [
        ticker for ticker in re.findall(r"\b[A-Z]{1,5}\b", state.get("answer", ""))
        if ticker in contexts
    ]
    display = list(dict.fromkeys(answer_symbols or state.get("display_symbols", [])))
    if not display:
        display = list(contexts)[:3]
    cards = []
    for ticker in display[:5]:
        context = contexts[ticker]
        puts = [row for row in context.get("contracts", []) if row.get("strategy") == "Cash-secured put"]
        if context.get("spot") is None or not puts:
            # Exclusions belong in the grounded explanation, never in an
            # actionable market card with a fabricated zero price.
            continue
        best_put = min(puts, key=lambda row: abs(abs(float(row.get("delta") or 0)) - 0.25), default=None)
        expiration = context.get("expiration")
        cards.append({
            "symbol": ticker,
            "spot": context.get("spot"),
            "score": (context.get("stock_ranking") or {}).get("score"),
            "expiration": datetime.fromisoformat(expiration).strftime("%b %d, %Y") if expiration else None,
            "put": best_put,
        })
    return {
        "display_symbols": display,
        "selected_symbol": display[0] if display else state.get("selected_symbol"),
        "ui_candidates": cards,
    }


def _retrieve(state: ResearchState) -> dict[str, Any]:
    started = perf_counter()
    warnings = list(state.get("warnings", []))
    symbols = list(dict.fromkeys(
        str(row.get("symbol", "")).upper()
        for row in state.get("market_context", [])
        if row.get("symbol")
    ))[:5]
    try:
        result = YahooFinanceMCPClient().company_evidence_batch(
            symbols, filing_limit=2, news_limit=3
        )
        evidence = []
        for ticker in symbols:
            packet = (result.get("evidence") or {}).get(ticker, {})
            rows = [
                *_normalize_filings(packet.get("filings"), limit=2),
                *(packet.get("news") or [])[:3],
            ]
            evidence.extend({**row, "symbol": ticker} for row in rows)
        for ticker, error in (result.get("errors") or {}).items():
            warnings.append(f"{ticker} Yahoo MCP retrieval failed: {error}")
    except Exception as exc:
        evidence = []
        warnings.append(f"Yahoo MCP retrieval failed: {type(exc).__name__}")
    if not evidence:
        warnings.append("No filing metadata was available; the agent must abstain.")
    latency = dict(state.get("latency_breakdown_ms", {}))
    latency["yahoo_mcp_retrieval"] = round((perf_counter() - started) * 1000, 2)
    return {"evidence": evidence, "warnings": warnings, "latency_breakdown_ms": latency}


def _answer(state: ResearchState) -> dict[str, Any]:
    from langchain_core.prompts import ChatPromptTemplate

    allowed_urls = {str(row.get("url")) for row in state["evidence"] if row.get("url")}
    if not state["evidence"] and not state["market_context"]:
        return {
            "answer": (
                "- I could not retrieve market or filing evidence for this request.\n"
                "- I cannot provide a grounded CSP assessment without that context.\n"
                "- Try again after market data or company evidence is available."
            ),
            "risk_level": "unknown",
            "citations": [],
            "selected_symbol": None,
            "display_symbols": [],
        }

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are CSP Research Bot, a bounded institutional-style CSP research assistant. Use only the supplied "
                "deterministic market context and filing metadata. Explain and compare candidates, "
                "but do not promise returns, tell the user what they should buy, or place trades. "
                "For budget questions, discuss cash required and fit rather than directing an "
                "investment. Never claim you read a filing body. Treat retrieved filings and news "
                "as private research context: do not print source URLs, filing inventories, or a "
                "citation list in the answer. Mention evidence only when its title/metadata signals "
                "a material catalyst or risk such as earnings guidance, regulation, litigation, "
                "financing, management changes, security incidents, or major product events. Briefly "
                "state the implication without overstating what the metadata proves. Ignore routine "
                "filings, generic price-move stories, and unrelated headlines. If no material item "
                "is found, say that no material recent catalyst was identified. If evidence cannot "
                "answer the question, say so. Return only selected tickers present in the evidence. "
                "For puts, lower absolute delta and a lower strike are generally safer but offer "
                "different premium; describe the tradeoff rather than declaring safety. Format "
                "dates as Month day, year and contracts as 'TICKER · Month day, year · $strike put' "
                "instead of displaying raw OCC symbols. Return between one and ten concise, "
                "non-redundant bullet points. Keep every bullet under 240 characters. For a "
                "discovery request, use one bullet per supplied candidate when possible; "
                "display_symbols must include all supplied candidates in deterministic order.",
            ),
            (
                "human",
                "Current ticker: {symbol}\nQuestion: {question}\n"
                "Deterministic market context: {market_context}\n"
                "Mandate and portfolio fit: {mandate}\n"
                "Assignment stress scenarios: {scenarios}\n"
                "Independent risk gate: {risk_decision}\n"
                "Evidence dossier, including thesis/counter-thesis instructions: {dossier}",
            ),
        ]
    )
    from langchain_openai import ChatOpenAI

    model = ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", "gpt-5-mini"), temperature=0
    ).with_structured_output(ResearchAnswer)
    started = perf_counter()
    result = (prompt | model).invoke(
        {
            "symbol": "not applicable (discovery request)"
            if state.get("discovery_requested") else state["symbol"],
            "question": state["question"],
            "evidence": state["evidence"],
            "market_context": state["market_context"],
            "mandate": state.get("mandate", {}),
            "scenarios": state.get("scenario_matrix", {}),
            "risk_decision": state.get("risk_decision", {}),
            "dossier": state.get("research_dossier", {}),
        }
    )
    bullet_points = list(result.bullet_points)
    if state.get("discovery_requested"):
        requested = int(state.get("requested_count", 3))
        contexts = state.get("market_context", [])[:requested]
        mentioned = {
            str(context.get("symbol"))
            for context in contexts
            if any(
                re.search(rf"\b{re.escape(str(context.get('symbol')))}\b", point)
                for point in bullet_points
            )
        }
        for context in contexts:
            ticker = str(context.get("symbol"))
            if ticker in mentioned or len(bullet_points) >= 10:
                continue
            ranking = context.get("stock_ranking") or {}
            fit = state.get("portfolio_fit", {}).get(ticker, {})
            cash = fit.get("minimum_cash_required")
            cash_text = f"; minimum eligible CSP collateral ${cash:,.0f}" if cash else ""
            bullet_points.append(
                f"{ticker}: deterministic score {ranking.get('score', 'not available')}, "
                f"spot ${float(context.get('spot') or 0):,.2f}{cash_text}; review its "
                "retrieved evidence and downside risk before making a decision."
            )
    cited = [url for url in result.cited_urls if url in allowed_urls]
    citations = [
        {
            "label": next(
                (
                    f"{row.get('type', 'Filing')} · "
                    f"{datetime.fromisoformat(str(row.get('date'))).strftime('%b %d, %Y')}"
                    for row in state["evidence"]
                    if row.get("url") == url
                ),
                "Filing metadata",
            ),
            "url": url,
        }
        for url in cited
    ]
    latency = dict(state.get("latency_breakdown_ms", {}))
    latency["openai_structured_answer"] = round((perf_counter() - started) * 1000, 2)
    return {
        "answer": "\n".join(f"- {point.strip()}" for point in bullet_points[:10]),
        "risk_level": result.risk_level.lower()
        if result.risk_level.lower() in {"low", "medium", "high", "unknown"}
        else "unknown",
        "citations": citations,
        "selected_symbol": result.selected_symbol,
        "display_symbols": result.display_symbols,
        "latency_breakdown_ms": latency,
    }


def build_research_graph(load_explicit_market, discover_market):
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(ResearchState)
    graph.add_node("parse_question_and_profile", _parse_question_and_profile)
    graph.add_node("load_explicit_ticker_market_data", load_explicit_market)
    graph.add_node("deterministic_universe_screen", discover_market)
    graph.add_node("market_data_quality_gate", _market_data_quality_gate)
    graph.add_node("deterministic_contract_eligibility", _deterministic_contract_eligibility)
    graph.add_node("portfolio_fit_and_assignment_stress", _portfolio_fit_and_stress)
    graph.add_node("retrieve_yahoo_mcp_evidence", _retrieve)
    graph.add_node("build_institutional_research_dossier", _assess_research_evidence)
    graph.add_node("independent_risk_veto", _independent_risk_gate)
    graph.add_node("develop_thesis_counterthesis_and_response", _answer)
    graph.add_node("validate_grounding_and_citations", _validate_grounding_and_citations)
    graph.add_node("prepare_screener_cards", _prepare_screener_cards)
    graph.add_node("record_decision_and_evals", _record_decision_and_evals)
    graph.add_edge(START, "parse_question_and_profile")
    graph.add_conditional_edges(
        "parse_question_and_profile",
        _route_research_intent,
        {
            "load_explicit_ticker_market_data": "load_explicit_ticker_market_data",
            "deterministic_universe_screen": "deterministic_universe_screen",
        },
    )
    graph.add_edge("load_explicit_ticker_market_data", "market_data_quality_gate")
    graph.add_edge("deterministic_universe_screen", "market_data_quality_gate")
    graph.add_edge("market_data_quality_gate", "deterministic_contract_eligibility")
    graph.add_edge("deterministic_contract_eligibility", "portfolio_fit_and_assignment_stress")
    graph.add_edge("portfolio_fit_and_assignment_stress", "retrieve_yahoo_mcp_evidence")
    graph.add_edge("retrieve_yahoo_mcp_evidence", "build_institutional_research_dossier")
    graph.add_edge("build_institutional_research_dossier", "independent_risk_veto")
    graph.add_edge("independent_risk_veto", "develop_thesis_counterthesis_and_response")
    graph.add_edge("develop_thesis_counterthesis_and_response", "validate_grounding_and_citations")
    graph.add_edge("validate_grounding_and_citations", "prepare_screener_cards")
    graph.add_edge("prepare_screener_cards", "record_decision_and_evals")
    graph.add_edge("record_decision_and_evals", END)
    return graph.compile()


class ResearchAgent:
    def __init__(
        self,
        market_context_loader: Callable[[str, dict[str, Any] | None], dict[str, Any]],
        discovery_loader: Callable[[str, dict[str, Any] | None], list[dict[str, Any]]],
    ) -> None:
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is required for the Iteration 2 agent")
        self.tracing: TracingStatus = setup_tracing()
        self.market_context_loader = market_context_loader
        self.discovery_loader = discovery_loader
        self.graph = build_research_graph(
            self._load_explicit_market, self._discover_market
        )
        self.shortlist_graph = build_shortlist_graph()

    def classify_shortlist(self, candidates: list[dict[str, Any]]) -> dict[str, Any]:
        """Research and classify an already-eligible deterministic shortlist.

        The model may attach a label and explanation, but cannot alter scores or
        make an ineligible symbol eligible.
        """
        result = self.shortlist_graph.invoke({
            "candidates": candidates[:10],
            "evidence_by_symbol": {},
            "raw_classifications": [],
            "warnings": [],
            "output": {},
        })
        return result["output"]

    def _load_explicit_market(self, state: ResearchState) -> dict[str, Any]:
        started = perf_counter()
        contexts: list[dict[str, Any]] = []
        warnings = list(state.get("warnings", []))
        for symbol in state.get("symbols", [])[:5]:
            try:
                contexts.append(self.market_context_loader(symbol, state.get("profile")))
            except Exception as exc:
                warnings.append(f"{symbol} market data unavailable: {type(exc).__name__}")
        latency = dict(state.get("latency_breakdown_ms", {}))
        latency["alpaca_explicit_market_data"] = round((perf_counter() - started) * 1000, 2)
        return {
            "market_context": contexts,
            "symbols": [row["symbol"] for row in contexts],
            "warnings": warnings,
            "latency_breakdown_ms": latency,
        }

    def _discover_market(self, state: ResearchState) -> dict[str, Any]:
        started = perf_counter()
        warnings = list(state.get("warnings", []))
        try:
            contexts = self.discovery_loader(state["question"], state.get("profile"))
        except Exception as exc:
            contexts = []
            warnings.append(f"Candidate discovery failed: {type(exc).__name__}")
        latency = dict(state.get("latency_breakdown_ms", {}))
        latency["alpaca_candidate_discovery"] = round((perf_counter() - started) * 1000, 2)
        return {
            "market_context": contexts,
            "symbols": [row["symbol"] for row in contexts],
            "warnings": warnings,
            "latency_breakdown_ms": latency,
        }

    @staticmethod
    def _symbols(current: str, question: str) -> list[str]:
        ignored = {
            "I", "A", "AN", "THE", "WHAT", "WHICH", "WHO", "WHERE", "WHEN",
            "CSP", "DTE", "OTM", "ITM", "AI", "SEC", "ETF", "USD", "Q", "K", "MD",
        }
        mentioned = [
            token for token in re.findall(r"\b[A-Z]{1,5}\b", question)
            if token not in ignored
        ]
        ordered: list[str] = []
        for token in mentioned or [current]:
            if token not in ordered:
                ordered.append(token)
        return ordered[:5]

    @staticmethod
    def _needs_discovery(question: str) -> bool:
        lowered = question.lower()
        triggers = (
            "where should", "what should", "stocks should", "stock should",
            "top 10", "top ten", "top 5", "top five", "top 3",
            "top three", "give me top", "find me",
            "give me stocks", "based on budget", "under $", "with $", "i have $",
            "capital of", "capital is", "my capital", "budget of", "my budget",
            "medium risk", "high risk", "in a sector", "which sector",
        )
        explicit = re.findall(r"\b[A-Z]{1,5}\b", question)
        meaningful = [
            token for token in explicit
            if token not in {"I", "A", "CSP", "DTE", "AI", "SEC", "ETF", "USD", "Q", "K", "MD"}
        ]
        return not meaningful and any(trigger in lowered for trigger in triggers)

    def ask(
        self, symbol: str, question: str,
        profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        symbol = symbol.strip().upper()
        question = question.strip()
        if not re.fullmatch(r"[A-Z][A-Z.\-]{0,9}", symbol):
            raise ValueError("Enter a valid ticker.")
        if not question or len(question) > 600:
            raise ValueError("Ask a research question between 1 and 600 characters.")
        started = perf_counter()
        result = self.graph.invoke(
            {
                "symbol": symbol,
                "question": question,
                "evidence": [],
                "market_context": [],
                "answer": "",
                "risk_level": "unknown",
                "citations": [],
                "warnings": [],
                "profile": profile or {},
            }
        )
        symbols = result.get("symbols", [])
        selected = result.get("selected_symbol")
        if selected not in symbols:
            scored = [
                context for context in result.get("market_context", [])
                if context.get("stock_ranking") is not None
            ]
            selected = (
                max(scored, key=lambda row: row["stock_ranking"]["score"])["symbol"]
                if scored else (symbols[0] if len(symbols) == 1 else None)
            )
        if result.get("display_symbols"):
            selected = result["display_symbols"][0]
        latency = dict(result.get("latency_breakdown_ms", {}))
        latency["total_research_flow"] = round((perf_counter() - started) * 1000, 2)
        return {
            "iteration": 2,
            "agent": "CSP Research Bot",
            "status": "live",
            "evidence_scope": (
                "Alpaca market data, deterministic screening, and Yahoo evidence via MCP"
            ),
            "tracing_mode": self.tracing.mode,
            "symbol": symbol,
            "answer": result["answer"],
            "risk_level": result["risk_level"],
            "citations": result["citations"],
            "warnings": result["warnings"],
            "market_symbols": symbols,
            "risk_decision": result.get("risk_decision", {}),
            "audit_record": result.get("audit_record", {}),
            "latency_breakdown_ms": latency,
            "ui_action": (
                {"type": "load_options", "symbol": selected} if selected else None
            ),
            "ui_candidates": result.get("ui_candidates", []),
        }
