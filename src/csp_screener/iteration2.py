from __future__ import annotations

import os
import re
from datetime import date, datetime
from typing import Annotated, Any, Callable, TypedDict

from pydantic import BaseModel, Field

from .course_e2e import _normalize_filings
from .observability import TracingStatus, setup_tracing
from .providers import TavilyMCPClient, YahooFinanceMCPClient
from .parsing import (
    extract_company_names,
    extract_mentioned_tickers,
    parse_budget,
    parse_expiration_date,
    parse_requested_count,
)


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
    company_names: list[str]
    requested_expiration: str | None
    budget: float | None
    requested_count: int
    intent: str
    source_intent: str
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
        and row.get("eligible_call_count", 0) >= 5
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
            and row.get("eligible_call_count", 0) >= 5
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
    tickers = extract_mentioned_tickers(question)
    company_names = extract_company_names(question)
    expiration = parse_expiration_date(question)
    if discovery:
        symbols: list[str] = []
    elif tickers:
        symbols = tickers
    elif company_names:
        symbols = []
    else:
        symbols = [symbol]
    budget = parse_budget(question)
    requested_count = parse_requested_count(question)
    return {
        "symbol": symbol,
        "question": question,
        "symbols": symbols,
        "company_names": company_names,
        "requested_expiration": expiration.isoformat() if expiration else None,
        "discovery_requested": discovery,
        "intent": "candidate_discovery" if discovery else "ticker_research",
        "budget": budget,
        "requested_count": requested_count,
        "mandate": {
            "budget": budget,
            "requested_count": requested_count,
            "strategy": "cash_secured_put",
            "risk_tolerance": next(
                (risk for risk in ("low", "medium", "high") if f"{risk} risk" in question.lower()),
                "unspecified",
            ),
            "willing_to_own_underlying": "unknown",
            "decision_scope": "research_only",
        },
    }


_OPTIONS_TERMS = (
    "csp", "cash-secured", "cash secured", "covered call", "option chain",
    "option", "put", "call", "dte", "delta", "strike", "premium",
    "collateral", "assignment", "otm", "itm",
)
_NEWS_TERMS = (
    "latest news", "recent news", "stock news", "company news",
    "headline", "headlines", "what happened", "announcement",
    "press release", "catalyst", "news",
)


def classify_source_intent(
    question: str,
    *,
    discovery: bool = False,
    named_subject: bool = False,
) -> str:
    """Route option-contract questions to Alpaca; all other chat research to Tavily."""
    lowered = question.lower()
    has_options = discovery or any(
        _question_has_term(lowered, term) for term in _OPTIONS_TERMS
    )
    has_news = any(_question_has_term(lowered, term) for term in _NEWS_TERMS)
    if has_options and (has_news or (named_subject and not discovery)):
        return "both"
    if has_options:
        return "options"
    return "news"


def _question_has_term(text: str, term: str) -> bool:
    if " " in term or "-" in term:
        return term in text
    return bool(re.search(rf"\b{re.escape(term)}s?\b", text))


def _classify_question_source(state: ResearchState) -> dict[str, Any]:
    return {
        "source_intent": classify_source_intent(
            state.get("question", ""),
            discovery=bool(state.get("discovery_requested")),
            named_subject=bool(state.get("symbols") or state.get("company_names")),
        )
    }


def _route_research_intent(state: ResearchState) -> str:
    return "deterministic_universe_screen" if state.get("discovery_requested") else "load_explicit_ticker_market_data"


def _route_after_classify(state: ResearchState) -> str:
    if state.get("source_intent") == "news":
        return "retrieve_tavily_news"
    return _route_research_intent(state)


def _route_after_market(state: ResearchState) -> str:
    if state.get("source_intent") == "both":
        return "retrieve_tavily_news"
    return "build_institutional_research_dossier"


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
            if contract.get("delta") is None and not state.get("requested_expiration"):
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
    news_only = state.get("source_intent") == "news"
    if not news_only and state.get("data_quality", {}).get("status") != "usable":
        reasons.append("insufficient_market_data")
    if not news_only and not any(
        row.get("eligible") for row in state.get("eligibility_ledger", [])
    ):
        reasons.append("no_eligible_contracts")
    if (
        not news_only
        and state.get("budget") is not None
        and not any(row.get("affordable") for row in state.get("portfolio_fit", {}).values())
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
        "source_intent": state.get("source_intent"),
        "route": "discovery" if state.get("discovery_requested") else "explicit_ticker",
        "symbols": state.get("symbols", []),
        "eligible_contract_count": sum(bool(row.get("eligible")) for row in state.get("eligibility_ledger", [])),
        "risk_status": state.get("risk_decision", {}).get("status"),
        "risk_reason_codes": state.get("risk_decision", {}).get("reason_codes", []),
        "citation_precision": round(sum(row.get("url") in allowed for row in citations) / len(citations), 3) if citations else 1.0,
        "format_compliance": 1 <= len(state.get("answer", "").splitlines()) <= 10,
        "ranking_authority": "deterministic",
    }}


def _validate_grounding_and_citations(state: ResearchState) -> dict[str, Any]:
    allowed_urls = {str(row.get("url")) for row in state.get("evidence", []) if row.get("url")}
    citations = [row for row in state.get("citations", []) if row.get("url") in allowed_urls]
    lines = [line for line in state.get("answer", "").splitlines() if line.strip()]
    if not 1 <= len(lines) <= 10 or any(not line.startswith("- ") for line in lines):
        raise ValueError("Research response must contain between one and ten bullet points.")
    context_symbols = {
        str(row.get("symbol"))
        for row in state.get("market_context", [])
        if row.get("symbol")
    }
    if not context_symbols:
        context_symbols = {
            str(symbol).upper()
            for symbol in [*state.get("symbols", []), state.get("symbol")]
            if symbol
        }
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
    if state.get("source_intent") == "news":
        display = list(dict.fromkeys(
            str(symbol).upper()
            for symbol in [*state.get("display_symbols", []), *state.get("symbols", []), state.get("symbol")]
            if symbol
        ))
        return {
            "display_symbols": display,
            "selected_symbol": display[0] if display else state.get("selected_symbol"),
            "ui_candidates": [],
        }
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


def _retrieve_tavily_news(state: ResearchState) -> dict[str, Any]:
    warnings = list(state.get("warnings", []))
    question = str(state.get("question", "")).strip()
    if not question:
        warnings.append("No question was available for Tavily news retrieval.")
        return {"evidence": [], "warnings": warnings}
    try:
        result = TavilyMCPClient().search_news(question, max_results=5)
        if result.get("error"):
            warnings.append(f"Tavily retrieval failed: {result['error']}")
        evidence = list(result.get("news") or [])[:5]
    except Exception as exc:
        evidence = []
        warnings.append(f"Tavily MCP retrieval failed: {type(exc).__name__}")
    if not evidence:
        warnings.append("No Tavily news was available; the agent must abstain.")
    return {"evidence": evidence, "warnings": warnings}


def _evidence_label(row: dict[str, Any]) -> str:
    kind = str(row.get("type") or "News")
    raw_date = row.get("date")
    if not raw_date:
        return kind
    try:
        return f"{kind} · {datetime.fromisoformat(str(raw_date)).strftime('%b %d, %Y')}"
    except ValueError:
        return kind


def _retrieve(state: ResearchState) -> dict[str, Any]:
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
    return {"evidence": evidence, "warnings": warnings}


def _answer(state: ResearchState) -> dict[str, Any]:
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_openai import ChatOpenAI

    allowed_urls = {str(row.get("url")) for row in state["evidence"] if row.get("url")}
    if not state["evidence"] and not state["market_context"]:
        source = "news" if state.get("source_intent") == "news" else "market or filing"
        return {
            "answer": (
                f"- I could not retrieve {source} evidence for this request.\n"
                "- I cannot provide a grounded assessment without that context.\n"
                "- Try again after market data or company evidence is available."
            ),
            "risk_level": "unknown",
            "citations": [],
            "selected_symbol": None,
            "display_symbols": [],
        }

    news_only = state.get("source_intent") == "news"
    if news_only:
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a stock and financial-analysis research assistant. Use only the "
                    "supplied Tavily news evidence to answer the user's question as written. "
                    "Cover any company, ticker, or market topic they named. Do not mention "
                    "or summarize any other company. Do not invent prices, option contracts, "
                    "or filings. Do not promise returns, tell the user what they should buy, "
                    "or place trades. Do not print source URLs. If the evidence cannot answer "
                    "the question, say so in three short bullets. Return between one and ten "
                    "concise, non-redundant bullet points under 240 characters each.",
                ),
                (
                    "human",
                    "Question: {question}\nTavily news evidence: {evidence}",
                ),
            ]
        )
        model = ChatOpenAI(
            model=os.getenv("OPENAI_MODEL", "gpt-5-mini"), temperature=0
        ).with_structured_output(ResearchAnswer)
        result = (prompt | model).invoke({
            "question": state["question"],
            "evidence": state["evidence"],
        })
        bullet_points = list(result.bullet_points)
        cited = [url for url in result.cited_urls if url in allowed_urls]
        citations = [
            {
                "label": next(
                    (
                        _evidence_label(row)
                        for row in state["evidence"]
                        if row.get("url") == url
                    ),
                    "News",
                ),
                "url": url,
            }
            for url in cited
        ]
        return {
            "answer": "\n".join(f"- {point.strip()}" for point in bullet_points[:10]),
            "risk_level": result.risk_level.lower()
            if result.risk_level.lower() in {"low", "medium", "high", "unknown"}
            else "unknown",
            "citations": citations,
            "selected_symbol": None,
            "display_symbols": [],
        }

    system_prompt = (
        "You are CSP Research Bot, a bounded institutional-style CSP research assistant. Use only the supplied "
        "deterministic market context and news evidence. Explain and compare candidates, "
        "but do not promise returns, tell the user what they should buy, or place trades. "
        "The screener ticker is only a UI default; answer with symbols present in market "
        "context, never substitute another company's contracts. If a requested expiration "
        "is present, report premiums for that date only and do not replace it with a later "
        "screener expiration. "
        "For budget questions, discuss cash required and fit rather than directing an "
        "investment. Never claim you read a filing body. Treat retrieved news "
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
        "display_symbols must include all supplied candidates in deterministic order."
    )
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system_prompt),
            (
                "human",
                "Question: {question}\n"
                "Selected screener ticker (UI default only): {symbol}\n"
                "Requested expiration: {requested_expiration}\n"
                "Deterministic market context: {market_context}\n"
                "Mandate and portfolio fit: {mandate}\n"
                "Assignment stress scenarios: {scenarios}\n"
                "Independent risk gate: {risk_decision}\n"
                "Evidence dossier: {dossier}",
            ),
        ]
    )
    model = ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", "gpt-5-mini"), temperature=0
    ).with_structured_output(ResearchAnswer)
    result = (prompt | model).invoke(
        {
            "symbol": "not applicable (discovery request)"
            if state.get("discovery_requested") else state["symbol"],
            "question": state["question"],
            "evidence": state["evidence"],
            "requested_expiration": state.get("requested_expiration") or "not specified",
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
                    _evidence_label(row)
                    for row in state["evidence"]
                    if row.get("url") == url
                ),
                "News",
            ),
            "url": url,
        }
        for url in cited
    ]
    return {
        "answer": "\n".join(f"- {point.strip()}" for point in bullet_points[:10]),
        "risk_level": result.risk_level.lower()
        if result.risk_level.lower() in {"low", "medium", "high", "unknown"}
        else "unknown",
        "citations": citations,
        "selected_symbol": result.selected_symbol,
        "display_symbols": result.display_symbols,
    }


def build_research_graph(load_explicit_market, discover_market):
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(ResearchState)
    graph.add_node("parse_question_and_profile", _parse_question_and_profile)
    graph.add_node("classify_question_source", _classify_question_source)
    graph.add_node("load_explicit_ticker_market_data", load_explicit_market)
    graph.add_node("deterministic_universe_screen", discover_market)
    graph.add_node("market_data_quality_gate", _market_data_quality_gate)
    graph.add_node("deterministic_contract_eligibility", _deterministic_contract_eligibility)
    graph.add_node("portfolio_fit_and_assignment_stress", _portfolio_fit_and_stress)
    graph.add_node("retrieve_tavily_news", _retrieve_tavily_news)
    graph.add_node("build_institutional_research_dossier", _assess_research_evidence)
    graph.add_node("independent_risk_veto", _independent_risk_gate)
    graph.add_node("develop_thesis_counterthesis_and_response", _answer)
    graph.add_node("validate_grounding_and_citations", _validate_grounding_and_citations)
    graph.add_node("prepare_screener_cards", _prepare_screener_cards)
    graph.add_node("record_decision_and_evals", _record_decision_and_evals)
    graph.add_edge(START, "parse_question_and_profile")
    graph.add_edge("parse_question_and_profile", "classify_question_source")
    graph.add_conditional_edges(
        "classify_question_source",
        _route_after_classify,
        {
            "retrieve_tavily_news": "retrieve_tavily_news",
            "load_explicit_ticker_market_data": "load_explicit_ticker_market_data",
            "deterministic_universe_screen": "deterministic_universe_screen",
        },
    )
    graph.add_edge("load_explicit_ticker_market_data", "market_data_quality_gate")
    graph.add_edge("deterministic_universe_screen", "market_data_quality_gate")
    graph.add_edge("market_data_quality_gate", "deterministic_contract_eligibility")
    graph.add_edge("deterministic_contract_eligibility", "portfolio_fit_and_assignment_stress")
    graph.add_conditional_edges(
        "portfolio_fit_and_assignment_stress",
        _route_after_market,
        {
            "retrieve_tavily_news": "retrieve_tavily_news",
            "build_institutional_research_dossier": "build_institutional_research_dossier",
        },
    )
    graph.add_edge("retrieve_tavily_news", "build_institutional_research_dossier")
    graph.add_edge("build_institutional_research_dossier", "independent_risk_veto")
    graph.add_edge("independent_risk_veto", "develop_thesis_counterthesis_and_response")
    graph.add_edge("develop_thesis_counterthesis_and_response", "validate_grounding_and_citations")
    graph.add_edge("validate_grounding_and_citations", "prepare_screener_cards")
    graph.add_edge("prepare_screener_cards", "record_decision_and_evals")
    graph.add_edge("record_decision_and_evals", END)
    return graph.compile()


def _evidence_scope(source_intent: str | None) -> str:
    if source_intent == "news":
        return "Tavily news via MCP"
    if source_intent == "options":
        return "Alpaca market data and deterministic screening"
    return "Alpaca market data, deterministic screening, and Tavily news via MCP"


class ResearchAgent:
    def __init__(
        self,
        market_context_loader: Callable[[str], dict[str, Any]],
        discovery_loader: Callable[[str], list[dict[str, Any]]],
        ticker_resolver: Callable[[str], str | None] | None = None,
    ) -> None:
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is required for the Iteration 2 agent")
        self.tracing: TracingStatus = setup_tracing()
        self.market_context_loader = market_context_loader
        self.discovery_loader = discovery_loader
        self.ticker_resolver = ticker_resolver or (lambda name: None)
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
        contexts: list[dict[str, Any]] = []
        warnings = list(state.get("warnings", []))
        symbols = list(state.get("symbols") or [])
        for name in state.get("company_names") or []:
            ticker = self.ticker_resolver(name)
            if ticker and ticker not in symbols:
                symbols.append(ticker)
            elif not ticker:
                warnings.append(f"Could not resolve {name} to a ticker for Alpaca.")
        if not symbols and not state.get("company_names"):
            current = str(state.get("symbol") or "").strip().upper()
            if current:
                symbols = [current]
        expiration = None
        raw_expiration = state.get("requested_expiration")
        if raw_expiration:
            try:
                expiration = date.fromisoformat(str(raw_expiration))
            except ValueError:
                warnings.append(f"Could not parse requested expiration {raw_expiration}.")
        for symbol in symbols[:5]:
            try:
                try:
                    contexts.append(self.market_context_loader(symbol, expiration))
                except TypeError:
                    contexts.append(self.market_context_loader(symbol))
            except Exception as exc:
                warnings.append(f"{symbol} market data unavailable: {type(exc).__name__}")
        return {
            "market_context": contexts,
            "symbols": [row["symbol"] for row in contexts],
            "symbol": contexts[0]["symbol"] if contexts else state.get("symbol"),
            "warnings": warnings,
        }

    def _discover_market(self, state: ResearchState) -> dict[str, Any]:
        warnings = list(state.get("warnings", []))
        try:
            contexts = self.discovery_loader(state["question"])
        except Exception as exc:
            contexts = []
            warnings.append(f"Candidate discovery failed: {type(exc).__name__}")
        return {
            "market_context": contexts,
            "symbols": [row["symbol"] for row in contexts],
            "warnings": warnings,
        }

    @staticmethod
    def _symbols(current: str, question: str) -> list[str]:
        mentioned = extract_mentioned_tickers(question)
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
        if extract_mentioned_tickers(question) or extract_company_names(question):
            return False
        return any(trigger in lowered for trigger in triggers)

    def ask(self, symbol: str, question: str) -> dict[str, Any]:
        symbol = symbol.strip().upper()
        question = question.strip()
        if not re.fullmatch(r"[A-Z][A-Z.\-]{0,9}", symbol):
            raise ValueError("Enter a valid ticker.")
        if not question or len(question) > 600:
            raise ValueError("Ask a research question between 1 and 600 characters.")
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
        source_intent = result.get("source_intent", "both")
        return {
            "iteration": 2,
            "agent": "CSP Research Bot",
            "status": "live",
            "source_intent": source_intent,
            "evidence_scope": _evidence_scope(source_intent),
            "tracing_mode": self.tracing.mode,
            "symbol": result.get("symbol") or (symbols[0] if symbols else symbol),
            "answer": result["answer"],
            "risk_level": result["risk_level"],
            "citations": result["citations"],
            "warnings": result["warnings"],
            "market_symbols": symbols,
            "risk_decision": result.get("risk_decision", {}),
            "audit_record": result.get("audit_record", {}),
            "ui_action": (
                {"type": "load_options", "symbol": selected}
                if selected and source_intent != "news" else None
            ),
            "ui_candidates": result.get("ui_candidates", []),
        }
