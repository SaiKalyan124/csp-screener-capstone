import pytest

from csp_screener.iteration2 import (
    ResearchAnswer,
    ResearchAgent,
    _answer,
    _parse_question_and_profile,
    _prepare_screener_cards,
    _prepare_eligible_shortlist,
    _retrieve,
    _route_research_intent,
    _validate_grounding_and_citations,
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


def test_research_answer_allows_up_to_ten_concise_bullets():
    result = ResearchAnswer(
        bullet_points=[f"Candidate {index}" for index in range(1, 11)],
        risk_level="unknown",
        cited_urls=[],
        selected_symbol=None,
        display_symbols=[],
    )
    assert len(result.bullet_points) == 10
    with pytest.raises(ValueError):
        ResearchAnswer(
            bullet_points=[f"Candidate {index}" for index in range(11)],
            risk_level="unknown",
            cited_urls=[],
            selected_symbol=None,
            display_symbols=[],
        )


def test_agent_extracts_multiple_tickers_for_comparison():
    assert ResearchAgent._symbols(
        "MU", "Screen these tickers for CSP: NVDA, AMD, INTC."
    ) == ["NVDA", "AMD", "INTC"]


def test_filing_form_names_are_not_misread_as_tickers():
    assert ResearchAgent._symbols("MU", "What is a 10-Q and how should I read its MD&A?") == ["MU"]


def test_agent_detects_budget_request_as_discovery():
    assert ResearchAgent._needs_discovery(
        "I want medium risk ideas and I have $40,000. What are three CSP candidates?"
    )


def test_agent_detects_top_three_capital_wording_as_discovery():
    assert ResearchAgent._needs_discovery(
        "give me top 3 csp trades for now i have capital of 50k"
    )


def test_agent_detects_five_stock_request_without_treating_i_as_a_ticker():
    question = "What 5 stocks should I buy now"
    assert ResearchAgent._needs_discovery(question)
    assert ResearchAgent._symbols("MU", question) == ["MU"]


def test_graph_parser_routes_explicit_ticker_research():
    state = _parse_question_and_profile({
        "symbol": "mu",
        "question": "Compare MU with AMD for CSP.",
    })
    assert state["symbols"] == ["MU", "AMD"]
    assert state["intent"] == "ticker_research"
    assert _route_research_intent(state) == "load_explicit_ticker_market_data"


def test_graph_parser_routes_discovery_and_extracts_budget():
    state = _parse_question_and_profile({
        "symbol": "MU",
        "question": "Give me top 3 CSP ideas with $50,000.",
    })
    assert state["symbols"] == []
    assert state["budget"] == 50000
    assert state["requested_count"] == 3
    assert _route_research_intent(state) == "deterministic_universe_screen"


def test_graph_parser_uses_profile_position_limit_when_question_has_no_budget():
    state = _parse_question_and_profile({
        "symbol": "MU",
        "question": "What do you think of MU?",
        "profile": {
            "mode": "custom",
            "risk_level": "low",
            "available_capital": 80_000,
            "max_allocation_pct": 25,
            "dte_min": 30,
            "dte_max": 45,
            "delta_min": 0.10,
            "delta_max": 0.20,
            "avoid_earnings": True,
        },
    })
    assert state["budget"] == 20_000
    assert state["mandate"]["risk_tolerance"] == "low"
    assert state["mandate"]["delta_range"] == [0.10, 0.20]


def test_retrieval_fetches_evidence_for_every_market_candidate(monkeypatch):
    class FakeYahooClient:
        def company_evidence_batch(self, symbols, filing_limit, news_limit):
            assert symbols == ["NFLX", "GOOGL", "MU"]
            return {
                "evidence": {
                    symbol: {
                        "filings": [{"type": "10-Q", "url": f"https://example.test/{symbol}"}],
                        "news": [],
                    }
                    for symbol in symbols
                },
                "errors": {},
            }

    monkeypatch.setattr("csp_screener.iteration2.YahooFinanceMCPClient", FakeYahooClient)
    result = _retrieve({
        "symbol": "MU",
        "symbols": ["NFLX", "GOOGL", "MU"],
        "market_context": [
            {"symbol": "NFLX"}, {"symbol": "GOOGL"}, {"symbol": "MU"}
        ],
        "warnings": [],
    })
    assert [row["symbol"] for row in result["evidence"]] == ["NFLX", "GOOGL", "MU"]


def test_discovery_cards_keep_all_requested_candidates():
    result = _validate_grounding_and_citations({
        "answer": "- One\n- Two\n- Three",
        "evidence": [],
        "discovery_requested": True,
        "requested_count": 5,
        "market_context": [
            {"symbol": symbol}
            for symbol in ["NFLX", "MSFT", "META", "AVGO", "INTC"]
        ],
        "display_symbols": ["NFLX", "MSFT", "META"],
        "selected_symbol": "NFLX",
    })
    assert result["display_symbols"] == ["NFLX", "MSFT", "META", "AVGO", "INTC"]


def test_excluded_ticker_does_not_create_actionable_zero_price_card():
    result = _prepare_screener_cards({
        "answer": "- AAPL exceeds the active profile position limit.",
        "display_symbols": ["AAPL"],
        "market_context": [{
            "symbol": "AAPL",
            "spot": None,
            "contracts": [],
            "eligibility": "excluded",
            "rejection_reason": "Collateral exceeds the profile position limit.",
        }],
    })

    assert result["ui_candidates"] == []


def test_dashboard_graph_removes_ineligible_candidates_before_research():
    result = _prepare_eligible_shortlist({
        "candidates": [
            {"symbol": "MU", "option_eligible": True, "eligible_put_count": 5, "eligible_call_count": 5},
            {"symbol": "BKNG", "option_eligible": False, "eligible_put_count": 0, "eligible_call_count": 0},
        ],
        "warnings": [],
    })
    assert [row["symbol"] for row in result["candidates"]] == ["MU"]


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
