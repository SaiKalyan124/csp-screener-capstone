from types import SimpleNamespace

from csp_screener.providers.alpaca import AlpacaMarketDataProvider


def test_resolve_company_ticker_prefers_optionable_name_prefix() -> None:
    provider = AlpacaMarketDataProvider.__new__(AlpacaMarketDataProvider)
    provider._assets = [
        SimpleNamespace(
            symbol="APLE",
            name="Apple Hospitality REIT, Inc.",
            tradable=True,
            attributes=["has_options"],
        ),
        SimpleNamespace(
            symbol="AAPL",
            name="Apple Inc.",
            tradable=True,
            attributes=["has_options"],
        ),
        SimpleNamespace(
            symbol="NFLX",
            name="Netflix, Inc.",
            tradable=True,
            attributes=["has_options"],
        ),
    ]
    assert provider.resolve_company_ticker("Netflix") == "NFLX"
    assert provider.resolve_company_ticker("Apple") == "AAPL"
