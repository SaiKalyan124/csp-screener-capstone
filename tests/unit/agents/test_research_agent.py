from datetime import date

import pytest

from csp_screener.iteration2 import (
    ResearchAnswer,
    ResearchAgent,
    _answer,
    _classify_question_source,
    _independent_risk_gate,
    _parse_question_and_profile,
    _prepare_eligible_shortlist,
    _prepare_screener_cards,
    _retrieve,
    _retrieve_tavily_news,
    _route_after_classify,
    _route_after_market,
    _route_research_intent,
    classify_source_intent,
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


def test_news_question_routes_to_tavily_without_rewriting_the_company():
    state = _classified("MU", "What is the latest news of Apple?")
    assert state["symbol"] == "MU"
    assert state["company_names"] == ["Apple"]
    assert state["source_intent"] == "news"
    assert _route_after_classify(state) == "retrieve_tavily_news"


def test_explicit_market_loader_uses_resolved_company_not_dashboard_ticker():
    agent = ResearchAgent.__new__(ResearchAgent)
    loaded: list[tuple[str, date | None]] = []

    def loader(symbol, expiration=None):
        loaded.append((symbol, expiration))
        return {"symbol": symbol, "spot": 100, "contracts": []}

    agent.market_context_loader = loader
    agent.ticker_resolver = lambda name: "NFLX" if name.lower() == "netflix" else None
    result = agent._load_explicit_market({
        "symbol": "MU",
        "symbols": [],
        "company_names": ["Netflix"],
        "requested_expiration": "2026-09-04",
        "warnings": [],
    })
    assert result["symbols"] == ["NFLX"]
    assert result["symbol"] == "NFLX"
    assert loaded == [("NFLX", date(2026, 9, 4))]
    assert not any(symbol == "MU" for symbol, _ in loaded)


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


def _classified(symbol: str, question: str) -> dict:
    parsed = _parse_question_and_profile({"symbol": symbol, "question": question})
    return {**parsed, **_classify_question_source(parsed)}


def test_classifier_routes_option_questions_to_alpaca():
    state = _classified("MU", "Show me CSP puts and the option chain.")
    assert classify_source_intent(state["question"], discovery=True) == "options"
    assert classify_source_intent(
        "Show me CSP puts and the option chain for MU.", named_subject=True
    ) == "both"


def test_classifier_routes_named_company_options_through_alpaca_and_tavily():
    state = _classified(
        "MU", "What's the Netflix secured put stock options premium for 09/04?"
    )
    assert state["company_names"] == ["Netflix"]
    assert state["symbols"] == []
    assert state["source_intent"] == "both"
    lowered = _classified(
        "MU", "what is the netflix secured put premium for 09/04?"
    )
    assert lowered["company_names"] == ["netflix"]
    assert lowered["source_intent"] == "both"
    assert _route_after_classify(state) == "load_explicit_ticker_market_data"
    assert _route_after_market(state) == "retrieve_tavily_news"


def test_classifier_routes_news_questions_to_tavily():
    state = _classified("MU", "What is the latest news for MU?")
    assert state["source_intent"] == "news"
    assert _route_after_classify(state) == "retrieve_tavily_news"


def test_classifier_routes_mixed_questions_through_alpaca_then_tavily():
    state = _classified("MU", "Latest news and CSP candidates for MU")
    assert state["source_intent"] == "both"
    assert _route_after_classify(state) == "load_explicit_ticker_market_data"
    assert _route_after_market(state) == "retrieve_tavily_news"


def test_classifier_keeps_discovery_on_alpaca_options_path():
    state = _classified("MU", "Give me top 3 CSP ideas with $50,000.")
    assert state["source_intent"] == "options"
    assert _route_after_classify(state) == "deterministic_universe_screen"
    assert _route_after_market(state) == "build_institutional_research_dossier"


def test_classifier_defaults_general_research_to_tavily():
    assert classify_source_intent("What should I know about MU?") == "news"
    assert classify_source_intent("Analyze Boeing's latest earnings.") == "news"
    state = _classified("MU", "What is the latest news of Apple?")
    assert _route_after_classify(state) == "retrieve_tavily_news"


def test_news_only_risk_gate_does_not_veto_missing_contracts():
    result = _independent_risk_gate({
        "source_intent": "news",
        "data_quality": {},
        "eligibility_ledger": [],
        "portfolio_fit": {},
        "research_dossier": {"coverage": "sufficient"},
    })["risk_decision"]
    assert result["status"] == "pass"
    assert "no_eligible_contracts" not in result["reason_codes"]
    assert "insufficient_market_data" not in result["reason_codes"]


def test_tavily_retrieval_sends_the_raw_question(monkeypatch):
    class FakeTavilyClient:
        def search_news(self, query, max_results):
            assert query == "What is the latest news of Apple?"
            assert max_results == 5
            return {
                "query": query,
                "news": [{
                    "type": "News",
                    "title": "Apple reports earnings",
                    "url": "https://example.test/apple",
                }],
            }

    monkeypatch.setattr("csp_screener.iteration2.TavilyMCPClient", FakeTavilyClient)
    result = _retrieve_tavily_news({
        "symbol": "MU",
        "question": "What is the latest news of Apple?",
        "warnings": [],
    })
    assert result["evidence"][0]["title"] == "Apple reports earnings"
    assert result["evidence"][0]["url"] == "https://example.test/apple"


def test_news_only_screener_cards_are_empty():
    result = _prepare_screener_cards({
        "source_intent": "news",
        "symbol": "MU",
        "symbols": ["MU"],
        "display_symbols": ["MU"],
        "market_context": [],
        "answer": "- MU reported earnings.",
    })
    assert result["ui_candidates"] == []
    assert result["display_symbols"] == ["MU"]
