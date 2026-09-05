from csp_screener.iteration2 import _parse_question_and_profile
from csp_screener.tool_routing import route_research_tools


def test_portfolio_question_routes_to_saved_positions() -> None:
    positions = [
        {"underlying": "AAPL", "status": "OPEN", "current_mark": 2.1},
        {"underlying": "NVDA", "status": "OPEN", "current_mark": 3.2},
        {"underlying": "MU", "status": "CLOSED", "current_mark": 1.0},
    ]

    parsed = _parse_question_and_profile({
        "symbol": "MU",
        "question": "How is my portfolio doing?",
        "profile": {},
        "portfolio_positions": positions,
    })

    assert parsed["intent"] == "portfolio_review"
    assert parsed["symbols"] == ["AAPL", "NVDA"]
    assert parsed["discovery_requested"] is False
    assert parsed["mandate"]["portfolio_positions"] == positions[:2]


def test_portfolio_route_loads_store_before_market_research() -> None:
    route = route_research_tools("Review my holdings and assignment risk")

    assert route.intent == "portfolio_review"
    assert route.primary == ("portfolio_store", "alpaca_market_mcp")
