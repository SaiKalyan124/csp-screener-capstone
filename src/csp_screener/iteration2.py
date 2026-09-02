from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Annotated, Any, Callable, TypedDict

from pydantic import BaseModel, Field

from .course_e2e import _normalize_filings
from .observability import TracingStatus, setup_tracing


class ResearchState(TypedDict):
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


class ShortlistState(TypedDict):
    candidates: list[dict[str, Any]]
    evidence_by_symbol: dict[str, list[dict[str, Any]]]
    raw_classifications: list[dict[str, Any]]
    warnings: list[str]
    output: dict[str, Any]


class ResearchAnswer(BaseModel):
    bullet_points: list[
        Annotated[str, Field(min_length=1, max_length=240)]
    ] = Field(
        min_length=3,
        max_length=3,
        description=(
            "Exactly three concise, non-redundant bullets grounded only in supplied evidence"
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
    import yfinance as yf

    ticker = yf.Ticker(symbol)
    rows = _normalize_filings(ticker.get_sec_filings(), limit=2)
    try:
        for item in (ticker.news or [])[:3]:
            content = item.get("content", item)
            url = (content.get("canonicalUrl") or {}).get("url") or content.get("link")
            title = content.get("title")
            if title and url:
                rows.append({
                    "type": "News",
                    "title": title,
                    "date": content.get("pubDate"),
                    "url": url,
                })
    except Exception:
        pass
    return rows[:5]


def _retrieve_shortlist_evidence(state: ShortlistState) -> dict[str, Any]:
    evidence_by_symbol: dict[str, list[dict[str, Any]]] = {}
    warnings = list(state.get("warnings", []))
    bounded = state["candidates"][:10]
    with ThreadPoolExecutor(max_workers=min(5, len(bounded) or 1)) as pool:
        futures = {
            pool.submit(_candidate_evidence, row["symbol"]): row["symbol"]
            for row in bounded
        }
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                evidence_by_symbol[symbol] = future.result()
            except Exception as exc:
                evidence_by_symbol[symbol] = []
                warnings.append(f"{symbol} research unavailable: {type(exc).__name__}")
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
        model=os.getenv("OPENAI_MODEL", "gpt-5.6-luna"), temperature=0
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
    graph.add_node("retrieve_shortlist_evidence", _retrieve_shortlist_evidence)
    graph.add_node("classify_shortlist_with_llm", _classify_shortlist_with_llm)
    graph.add_node("validate_and_evaluate", _validate_shortlist_classification)
    graph.add_edge(START, "retrieve_shortlist_evidence")
    graph.add_edge("retrieve_shortlist_evidence", "classify_shortlist_with_llm")
    graph.add_edge("classify_shortlist_with_llm", "validate_and_evaluate")
    graph.add_edge("validate_and_evaluate", END)
    return graph.compile()


def _retrieve(state: ResearchState) -> dict[str, Any]:
    import yfinance as yf

    warnings: list[str] = []
    try:
        evidence_symbol = state["symbols"][0] if state["symbols"] else state["symbol"]
        evidence = _normalize_filings(yf.Ticker(evidence_symbol).get_sec_filings(), limit=5)
    except Exception as exc:
        evidence = []
        warnings.append(f"Filing metadata retrieval failed: {type(exc).__name__}")
    if not evidence:
        warnings.append("No filing metadata was available; the agent must abstain.")
    return {"evidence": evidence, "warnings": warnings}


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
                "You are Kezzy, a bounded CSP research assistant. Use only the supplied "
                "deterministic market context and filing metadata. Explain and compare candidates, "
                "but do not promise returns, tell the user what they should buy, or place trades. "
                "For budget questions, discuss cash required and fit rather than directing an "
                "investment. Never claim you read a filing body. If evidence cannot answer the "
                "question, say so. Return only URLs and selected tickers present in the evidence. "
                "For puts, lower absolute delta and a lower strike are generally safer but offer "
                "different premium; describe the tradeoff rather than declaring safety. Format "
                "dates as Month day, year and contracts as 'TICKER · Month day, year · $strike put' "
                "instead of displaying raw OCC symbols. Always return exactly three concise, "
                "non-redundant bullet points. Keep every bullet under 240 characters.",
            ),
            (
                "human",
                "Current ticker: {symbol}\nQuestion: {question}\n"
                "Deterministic market context: {market_context}\n"
                "Filing metadata: {evidence}",
            ),
        ]
    )
    from langchain_openai import ChatOpenAI

    model = ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", "gpt-5.6-luna"), temperature=0
    ).with_structured_output(ResearchAnswer)
    result = (prompt | model).invoke(
        {
            "symbol": state["symbol"],
            "question": state["question"],
            "evidence": state["evidence"],
            "market_context": state["market_context"],
        }
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
    return {
        "answer": "\n".join(f"- {point.strip()}" for point in result.bullet_points),
        "risk_level": result.risk_level.lower()
        if result.risk_level.lower() in {"low", "medium", "high", "unknown"}
        else "unknown",
        "citations": citations,
        "selected_symbol": result.selected_symbol,
        "display_symbols": result.display_symbols,
    }


def build_research_graph(gather_market):
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(ResearchState)
    graph.add_node("gather_market_context", gather_market)
    graph.add_node("retrieve_filing_metadata", _retrieve)
    graph.add_node("generate_grounded_research", _answer)
    graph.add_edge(START, "gather_market_context")
    graph.add_edge("gather_market_context", "retrieve_filing_metadata")
    graph.add_edge("retrieve_filing_metadata", "generate_grounded_research")
    graph.add_edge("generate_grounded_research", END)
    return graph.compile()


class ResearchAgent:
    def __init__(
        self,
        market_context_loader: Callable[[str], dict[str, Any]],
        discovery_loader: Callable[[str], list[dict[str, Any]]],
    ) -> None:
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is required for the Iteration 2 agent")
        self.tracing: TracingStatus = setup_tracing()
        self.market_context_loader = market_context_loader
        self.discovery_loader = discovery_loader
        self.graph = build_research_graph(self._gather_market)
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

    def _gather_market(self, state: ResearchState) -> dict[str, Any]:
        contexts: list[dict[str, Any]] = []
        warnings = list(state.get("warnings", []))
        if state["discovery_requested"]:
            try:
                contexts = self.discovery_loader(state["question"])
            except Exception as exc:
                warnings.append(f"Candidate discovery failed: {type(exc).__name__}")
        else:
            for symbol in state["symbols"][:5]:
                try:
                    contexts.append(self.market_context_loader(symbol))
                except Exception as exc:
                    warnings.append(f"{symbol} market data unavailable: {type(exc).__name__}")
        return {
            "market_context": contexts,
            "symbols": [row["symbol"] for row in contexts],
            "warnings": warnings,
        }

    @staticmethod
    def _symbols(current: str, question: str) -> list[str]:
        ignored = {"CSP", "DTE", "OTM", "ITM", "AI", "SEC", "ETF", "USD"}
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
            "where should", "what should", "top 10", "top ten", "top 3",
            "top three", "give me top", "find me",
            "give me stocks", "based on budget", "under $", "with $", "i have $",
            "capital of", "capital is", "my capital", "budget of", "my budget",
            "medium risk", "high risk", "in a sector", "which sector",
        )
        explicit = re.findall(r"\b[A-Z]{1,5}\b", question)
        meaningful = [token for token in explicit if token not in {"I", "CSP", "DTE", "AI"}]
        return not meaningful and any(trigger in lowered for trigger in triggers)

    def ask(self, symbol: str, question: str) -> dict[str, Any]:
        symbol = symbol.strip().upper()
        question = question.strip()
        if not re.fullmatch(r"[A-Z][A-Z.\-]{0,9}", symbol):
            raise ValueError("Enter a valid ticker.")
        if not question or len(question) > 600:
            raise ValueError("Ask a research question between 1 and 600 characters.")
        discovery_requested = self._needs_discovery(question)
        symbols = [] if discovery_requested else self._symbols(symbol, question)
        result = self.graph.invoke(
            {
                "symbol": symbol,
                "symbols": symbols,
                "question": question,
                "evidence": [],
                "market_context": [],
                "answer": "",
                "risk_level": "unknown",
                "citations": [],
                "warnings": [],
                "discovery_requested": discovery_requested,
            }
        )
        symbols = result.get("symbols", symbols)
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
        contexts_by_symbol = {
            row["symbol"]: row for row in result.get("market_context", [])
        }
        answer_symbols = [
            ticker for ticker in re.findall(r"\b[A-Z]{1,5}\b", result["answer"])
            if ticker in contexts_by_symbol
        ]
        display_symbols = [
            ticker for ticker in result.get("display_symbols", [])
            if ticker in contexts_by_symbol
        ]
        if answer_symbols:
            display_symbols = list(dict.fromkeys(answer_symbols))
        if not display_symbols:
            display_symbols = list(contexts_by_symbol)[:3]
        if display_symbols:
            selected = display_symbols[0]
        ui_candidates = []
        for ticker in display_symbols[:5]:
            context = contexts_by_symbol[ticker]
            puts = [
                row for row in context.get("contracts", [])
                if row.get("strategy") == "Cash-secured put"
            ]
            best_put = min(
                puts,
                key=lambda row: abs(abs(float(row.get("delta") or 0)) - 0.25),
                default=None,
            )
            ui_candidates.append(
                {
                    "symbol": ticker,
                    "spot": context.get("spot"),
                    "score": (context.get("stock_ranking") or {}).get("score"),
                    "expiration": datetime.fromisoformat(context["expiration"]).strftime("%b %d, %Y"),
                    "put": best_put,
                }
            )
        return {
            "iteration": 2,
            "agent": "Kezzy",
            "status": "live",
            "evidence_scope": "Alpaca market data, deterministic screening, and Yahoo filing metadata",
            "tracing_mode": self.tracing.mode,
            "symbol": symbol,
            "answer": result["answer"],
            "risk_level": result["risk_level"],
            "citations": result["citations"],
            "warnings": result["warnings"],
            "market_symbols": symbols,
            "ui_action": (
                {"type": "load_options", "symbol": selected} if selected else None
            ),
            "ui_candidates": ui_candidates,
        }
