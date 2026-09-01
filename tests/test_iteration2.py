import pytest

from csp_screener.iteration2 import ResearchAgent, _answer


def test_agent_rejects_invalid_ticker_before_graph_call():
    agent = ResearchAgent.__new__(ResearchAgent)
    agent.graph = None
    with pytest.raises(ValueError, match="valid ticker"):
        agent.ask("MU!", "What changed?")


def test_agent_rejects_oversized_question_before_graph_call():
    agent = ResearchAgent.__new__(ResearchAgent)
    agent.graph = None
    with pytest.raises(ValueError, match="1 and 600"):
        agent.ask("MU", "x" * 601)


def test_answer_abstains_without_evidence_or_model_call():
    result = _answer(
        {
            "symbol": "MU",
            "question": "What changed?",
            "evidence": [],
            "market_context": [],
            "answer": "",
            "risk_level": "unknown",
            "citations": [],
            "warnings": [],
        }
    )
    assert result["risk_level"] == "unknown"
    assert result["citations"] == []
    assert "cannot provide" in result["answer"]


def test_agent_extracts_multiple_tickers_for_comparison():
    assert ResearchAgent._symbols(
        "MU", "Screen these tickers for CSP: NVDA, AMD, INTC."
    ) == ["NVDA", "AMD", "INTC"]


def test_agent_detects_budget_request_as_discovery():
    assert ResearchAgent._needs_discovery(
        "I want medium risk ideas and I have $40,000. What are three CSP candidates?"
    )


def test_agent_detects_top_three_capital_wording_as_discovery():
    assert ResearchAgent._needs_discovery(
        "give me top 3 csp trades for now i have capital of 50k"
    )
