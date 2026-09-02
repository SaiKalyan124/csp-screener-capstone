from __future__ import annotations

import json
import os
from typing import Any, TypedDict

from dotenv import load_dotenv

from .observability import setup_tracing
from .providers import YahooFinanceMCPClient


class FlowState(TypedDict):
    symbol: str
    question: str
    evidence: list[dict[str, Any]]
    answer: str
    warnings: list[str]


def _normalize_filings(raw: Any, limit: int = 3) -> list[dict[str, Any]]:
    if not raw:
        return []
    if isinstance(raw, dict):
        candidates = raw.get("filings") or raw.get("data") or raw.get("items") or []
        if isinstance(candidates, dict):
            candidates = list(candidates.values())
    elif isinstance(raw, list):
        candidates = raw
    else:
        candidates = []

    normalized: list[dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "type": item.get("type") or item.get("formType") or item.get("form"),
                "date": item.get("date") or item.get("filingDate"),
                "title": item.get("title") or item.get("description"),
                "url": item.get("edgarUrl") or item.get("url"),
            }
        )
        if len(normalized) == limit:
            break
    return normalized


def _retrieve_filings(state: FlowState) -> dict[str, Any]:
    from opentelemetry import trace
    tracer = trace.get_tracer("csp-screener-capstone")
    warnings: list[str] = []
    evidence: list[dict[str, Any]] = []
    with tracer.start_as_current_span("mcp.yahoo.get_company_evidence") as span:
        span.set_attribute("ticker", state["symbol"])
        try:
            packet = YahooFinanceMCPClient().company_evidence(
                state["symbol"], filing_limit=3, news_limit=0
            )
            evidence = _normalize_filings(packet.get("filings"))
        except Exception as exc:
            warnings.append(f"Yahoo MCP evidence unavailable: {type(exc).__name__}")
        span.set_attribute("retrieval.document_count", len(evidence))
    return {"evidence": evidence, "warnings": warnings}


def _generate_answer(state: FlowState) -> dict[str, str]:
    from langchain_core.prompts import ChatPromptTemplate

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are a research assistant. Use only the supplied filing "
                "metadata. State clearly that metadata alone is not the filing body.",
            ),
            (
                "human",
                "Ticker: {symbol}\nQuestion: {question}\nEvidence: {evidence}",
            ),
        ]
    )

    if os.getenv("OPENAI_API_KEY"):
        from langchain_openai import ChatOpenAI

        model = ChatOpenAI(
            model=os.getenv("OPENAI_MODEL", "gpt-5-mini"),
            temperature=0,
        )
    else:
        from langchain_core.language_models.fake_chat_models import FakeListChatModel

        count = len(state["evidence"])
        model = FakeListChatModel(
            responses=[
                f"Dry-run: retrieved {count} SEC filing metadata record(s) for "
                f"{state['symbol']}. A production RAG answer must fetch and cite "
                "the corresponding SEC EDGAR filing bodies before summarizing risk."
            ]
        )

    message = (prompt | model).invoke(
        {
            "symbol": state["symbol"],
            "question": state["question"],
            "evidence": json.dumps(state["evidence"], default=str),
        }
    )
    return {"answer": message.content}


def build_graph():
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(FlowState)
    graph.add_node("retrieve_filing_metadata", _retrieve_filings)
    graph.add_node("generate_grounded_answer", _generate_answer)
    graph.add_edge(START, "retrieve_filing_metadata")
    graph.add_edge("retrieve_filing_metadata", "generate_grounded_answer")
    graph.add_edge("generate_grounded_answer", END)
    return graph.compile()


def run(symbol: str = "MU") -> dict[str, Any]:
    load_dotenv()
    tracing = setup_tracing()
    graph = build_graph()
    result = graph.invoke(
        {
            "symbol": symbol.upper(),
            "question": "What recent company disclosures should I review?",
            "evidence": [],
            "answer": "",
            "warnings": [],
        }
    )
    return {
        "tracing_mode": tracing.mode,
        "project_name": tracing.project_name,
        "symbol": result["symbol"],
        "evidence_count": len(result["evidence"]),
        "answer": result["answer"],
        "warnings": result["warnings"],
    }


def main() -> None:
    print(json.dumps(run(), indent=2))


if __name__ == "__main__":
    main()
