from datetime import datetime, timezone
from types import SimpleNamespace

from csp_screener.iteration1 import IterationOneConfig, IterationOneWorkflow


def _bars(count: int = 64):
    return [
        SimpleNamespace(
            close=100 * 1.001**index,
            volume=2_000_000,
            timestamp=datetime(2026, 8, 31, tzinfo=timezone.utc),
        )
        for index in range(count)
    ]


class FakeProvider:
    def daily_bars(self, symbols, start):
        return {symbol: _bars() for symbol in symbols}

    def latest_trade(self, symbol):
        return SimpleNamespace(
            price=100,
            timestamp=datetime(2026, 8, 31, tzinfo=timezone.utc),
        )

    def option_chain(self, symbol, **kwargs):
        chain = {}
        for kind in ("P", "C"):
            for strike in range(90, 111, 2):
                occ = f"{symbol}260918{kind}{strike * 1000:08d}"
                chain[occ] = SimpleNamespace(
                    latest_quote=SimpleNamespace(bid_price=1.0, ask_price=1.1),
                    implied_volatility=0.25,
                    greeks=SimpleNamespace(delta=-0.3 if kind == "P" else 0.3),
                )
        return chain


def test_iteration_one_screen_is_deterministic_and_bounded():
    workflow = IterationOneWorkflow(
        FakeProvider(), IterationOneConfig(universe=("MU", "AAPL"))
    )
    result = workflow.screen()
    assert result["iteration"] == 1
    assert result["workflow"] == "python-deterministic"
    assert [row["symbol"] for row in result["candidates"]] == ["AAPL", "MU"]


def test_iteration_one_options_returns_five_per_strategy():
    workflow = IterationOneWorkflow(
        FakeProvider(), IterationOneConfig(universe=("MU",))
    )
    result = workflow.options("MU")
    assert len(result["contracts"]) == 10
    assert [row["strategy"] for row in result["contracts"]] == (
        ["Cash-secured put"] * 5 + ["Covered call"] * 5
    )


def test_dashboard_excludes_stock_without_required_option_contracts():
    class PartiallyEligibleProvider(FakeProvider):
        def option_chain(self, symbol, **kwargs):
            chain = super().option_chain(symbol, **kwargs)
            return chain if symbol == "MU" else {}

    workflow = IterationOneWorkflow(
        PartiallyEligibleProvider(), IterationOneConfig(universe=("MU", "BKNG"))
    )
    result = workflow.screen()
    assert [row["symbol"] for row in result["candidates"]] == ["MU"]
    assert result["candidates"][0]["eligible_put_count"] == 5
    assert result["candidates"][0]["eligible_call_count"] == 5
    assert result["option_rejected_count"] == 1
