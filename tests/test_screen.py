from datetime import datetime, timezone
from types import SimpleNamespace

from csp_screener.screen import (
    parse_occ_symbol,
    rank_stock_candidates,
    screen_chain,
    select_csp_and_covered_calls,
    select_demo_calls,
)


def snapshot(bid: float, ask: float, delta: float = 0.5):
    return SimpleNamespace(
        latest_quote=SimpleNamespace(
            bid_price=bid,
            ask_price=ask,
            timestamp=datetime(2026, 8, 31, tzinfo=timezone.utc),
        ),
        implied_volatility=0.25,
        greeks=SimpleNamespace(delta=delta),
    )


def test_parse_occ_symbol():
    assert parse_occ_symbol("AAPL260116C00200000") == (
        "AAPL",
        datetime(2026, 1, 16).date(),
        "C",
        200.0,
    )


def test_screen_chain_filters_and_sorts_spreads():
    now = datetime(2026, 8, 31, 0, 0, 1, tzinfo=timezone.utc)
    rows = screen_chain(
        {
            "TIGHT": snapshot(1.00, 1.05),
            "WIDE": snapshot(1.00, 2.00),
            "ZERO": snapshot(0.00, 0.05),
        },
        now=now,
    )
    assert [row.symbol for row in rows] == ["TIGHT"]
    assert rows[0].quote_age_ms == 1000.0


def test_select_demo_calls_returns_five_each_nearest_spot():
    chain = {}
    for strike in range(90, 111, 2):
        symbol = f"XYZ260918C{strike * 1000:08d}"
        chain[symbol] = snapshot(1.0, 1.1)
    expiry, rows = select_demo_calls(chain, 100.0)
    assert expiry.isoformat() == "2026-09-18"
    assert [row["moneyness"] for row in rows] == ["ITM"] * 5 + ["OTM"] * 5
    assert [row["strike"] for row in rows[:2]] == [98.0, 96.0]


def test_rank_stock_candidates_applies_market_data_cuts_and_scores():
    def bars(price: float, daily_gain: float, volume: int, count: int = 64):
        return [
            SimpleNamespace(close=price * (1 + daily_gain) ** index, volume=volume)
            for index in range(count)
        ]

    rows = rank_stock_candidates(
        {
            "LIQUID": bars(100, 0.001, 2_000_000),
            "ILLIQUID": bars(20, 0.001, 10_000),
            "TOO_SHORT": bars(100, 0.001, 2_000_000, count=20),
        }
    )
    assert [row.symbol for row in rows] == ["LIQUID"]
    assert rows[0].avg_dollar_volume_m > 50
    assert 0 <= rows[0].score <= 100


def test_select_csp_and_covered_calls_returns_five_of_each():
    chain = {}
    for contract_type in ("P", "C"):
        for strike in range(90, 111, 2):
            symbol = f"XYZ260918{contract_type}{strike * 1000:08d}"
            chain[symbol] = snapshot(1.0, 1.1)
    expiry, rows = select_csp_and_covered_calls(chain, 100.0)
    assert expiry.isoformat() == "2026-09-18"
    assert [row["strategy"] for row in rows] == (
        ["Cash-secured put"] * 5 + ["Covered call"] * 5
    )
    assert all(row["moneyness"] == "OTM" for row in rows)
