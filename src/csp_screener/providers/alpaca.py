from __future__ import annotations

import re
import threading
from datetime import date, datetime
from typing import Any

from alpaca.data.historical import OptionHistoricalDataClient, StockHistoricalDataClient
from alpaca.data.requests import (
    OptionChainRequest,
    StockBarsRequest,
    StockLatestTradeRequest,
)
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import AssetClass, AssetStatus
from alpaca.trading.requests import GetAssetsRequest


class AlpacaMarketDataProvider:
    """Alpaca SDK adapter implementing the Iteration 1 provider protocol."""

    def __init__(self, key: str, secret: str) -> None:
        self._key = key
        self._secret = secret
        self.stocks = StockHistoricalDataClient(key, secret)
        self.options = OptionHistoricalDataClient(key, secret)
        self._assets: list[Any] | None = None
        self._assets_lock = threading.Lock()

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

    def resolve_company_ticker(self, name: str) -> str | None:
        """Map a company name to a tradable US equity ticker. Do not use for Tavily."""
        query = " ".join(name.strip().lower().split())
        if len(query) < 3:
            return None
        scored: list[tuple[int, int, int, str]] = []
        for asset in self._listed_equities():
            symbol = str(getattr(asset, "symbol", "") or "")
            asset_name = str(getattr(asset, "name", "") or "").lower()
            if not asset_name or not getattr(asset, "tradable", False):
                continue
            if not re.fullmatch(r"[A-Z][A-Z.\-]{0,9}", symbol):
                continue
            if asset_name == query or asset_name.startswith(f"{query} ") or asset_name.startswith(f"{query},"):
                rank = 0
            elif re.search(rf"\b{re.escape(query)}\b", asset_name):
                rank = 1
            else:
                continue
            attributes = getattr(asset, "attributes", None) or []
            optionable = 0 if "has_options" in attributes else 1
            scored.append((rank, optionable, len(symbol), symbol))
        scored.sort()
        return scored[0][3] if scored else None

    def _listed_equities(self) -> list[Any]:
        if self._assets is not None:
            return self._assets
        with self._assets_lock:
            try:
                for paper in (True, False):
                    try:
                        client = TradingClient(self._key, self._secret, paper=paper)
                        assets = list(client.get_all_assets(GetAssetsRequest(
                            status=AssetStatus.ACTIVE,
                            asset_class=AssetClass.US_EQUITY,
                        )) or [])
                    except Exception:
                        continue
                    if assets:
                        self._assets = assets
                        return self._assets
            except Exception:
                pass
            self._assets = []
            return self._assets
