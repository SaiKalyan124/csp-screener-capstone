from __future__ import annotations

from datetime import date, datetime

from alpaca.data.historical import OptionHistoricalDataClient, StockHistoricalDataClient
from alpaca.data.requests import (
    OptionChainRequest,
    StockBarsRequest,
    StockLatestTradeRequest,
)
from alpaca.data.timeframe import TimeFrame


class AlpacaMarketDataProvider:
    """Alpaca SDK adapter implementing the Iteration 1 provider protocol."""

    def __init__(self, key: str, secret: str) -> None:
        self.stocks = StockHistoricalDataClient(key, secret)
        self.options = OptionHistoricalDataClient(key, secret)

    def latest_trade(self, symbol: str):
        return self.stocks.get_stock_latest_trade(
            StockLatestTradeRequest(symbol_or_symbols=symbol)
        ).get(symbol)

    def option_chain(
        self,
        symbol: str,
        *,
        expiration_gte: date,
        expiration_lte: date,
        strike_gte: float,
        strike_lte: float,
    ):
        return self.options.get_option_chain(
            OptionChainRequest(
                underlying_symbol=symbol,
                expiration_date_gte=expiration_gte,
                expiration_date_lte=expiration_lte,
                strike_price_gte=strike_gte,
                strike_price_lte=strike_lte,
            )
        )

    def daily_bars(self, symbols: list[str], start: datetime):
        result = self.stocks.get_stock_bars(
            StockBarsRequest(
                symbol_or_symbols=symbols,
                timeframe=TimeFrame.Day,
                start=start,
            )
        )
        return {symbol: list(result.data.get(symbol, [])) for symbol in symbols}
