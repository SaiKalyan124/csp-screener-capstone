import pytest

from csp_screener.iteration2 import (
    ResearchAnswer,
    ResearchAgent,
    _answer,
    _validate_shortlist_classification,
)


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
    assert len(result["answer"].splitlines()) == 3
    assert all(line.startswith("- ") for line in result["answer"].splitlines())


def test_research_answer_requires_exactly_three_concise_bullets():
    with pytest.raises(ValueError):
        ResearchAnswer(
            bullet_points=["Only one bullet"],
            risk_level="unknown",
            cited_urls=[],
            selected_symbol=None,
            display_symbols=[],
        )


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


def test_shortlist_evaluations_preserve_eligibility_scores_and_citations():
    candidate = {
        "symbol": "MU",
        "score": 91,
        "option_eligible": True,
        "eligible_put_count": 5,
        "eligible_call_count": 5,
    }
    result = _validate_shortlist_classification({
        "candidates": [candidate],
        "evidence_by_symbol": {
            "MU": [{"url": "https://example.test/mu-filing"}]
        },
        "raw_classifications": [{
            "symbol": "MU",
            "classification": "watch",
            "reason": "Material event requires review.",
            "cited_urls": [
                "https://example.test/mu-filing",
                "https://invalid.test/invented",
            ],
        }],
        "warnings": [],
        "output": {},
    })["output"]
    assert result["candidates"][0]["score"] == 91
    assert result["candidates"][0]["research_citations"] == [
        "https://example.test/mu-filing"
    ]
    assert result["evaluation_scores"] == {
        "classification_coverage": 1.0,
        "eligible_symbol_precision": 1.0,
        "citation_precision": 0.5,
        "score_integrity": 1.0,
        "contract_eligibility_integrity": 1.0,
    }
