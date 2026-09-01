from __future__ import annotations

import statistics
import time
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any, Callable

from alpaca.data.historical import OptionHistoricalDataClient, StockHistoricalDataClient
from alpaca.data.requests import OptionChainRequest, StockLatestQuoteRequest

from .screen import quote_ages_ms, screen_chain


@dataclass(frozen=True)
class Timing:
    elapsed_ms: float
    item_count: int


def timed(call: Callable[[], Any]) -> tuple[Any, Timing]:
    started = time.perf_counter_ns()
    result = call()
    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
    return result, Timing(round(elapsed_ms, 2), len(result))


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def summarize(samples: list[Timing]) -> dict[str, float | int]:
    values = [sample.elapsed_ms for sample in samples]
    return {
        "runs": len(values),
        "min_ms": min(values),
        "median_ms": round(statistics.median(values), 2),
        "p95_ms": round(percentile(values, 0.95), 2),
        "max_ms": max(values),
        "last_item_count": samples[-1].item_count,
    }


def run_benchmark(
    api_key: str,
    secret_key: str,
    *,
    stocks: list[str],
    underlying: str,
    runs: int,
    warmups: int,
    dte_min: int,
    dte_max: int,
    strike_low: float | None,
    strike_high: float | None,
) -> dict[str, Any]:
    stock_client = StockHistoricalDataClient(api_key, secret_key)
    option_client = OptionHistoricalDataClient(api_key, secret_key)
    stock_request = StockLatestQuoteRequest(symbol_or_symbols=stocks)
    today = date.today()
    chain_request = OptionChainRequest(
        underlying_symbol=underlying,
        expiration_date_gte=today + timedelta(days=dte_min),
        expiration_date_lte=today + timedelta(days=dte_max),
        strike_price_gte=strike_low,
        strike_price_lte=strike_high,
    )

    for _ in range(warmups):
        stock_client.get_stock_latest_quote(stock_request)
        option_client.get_option_chain(chain_request)

    stock_samples: list[Timing] = []
    option_samples: list[Timing] = []
    screening_samples: list[Timing] = []
    latest_quotes: dict[str, Any] = {}
    latest_chain: dict[str, Any] = {}
    screened = []
    for _ in range(runs):
        latest_quotes, timing = timed(lambda: stock_client.get_stock_latest_quote(stock_request))
        stock_samples.append(timing)
        latest_chain, timing = timed(lambda: option_client.get_option_chain(chain_request))
        option_samples.append(timing)
        screened, timing = timed(lambda: screen_chain(latest_chain))
        screening_samples.append(timing)

    ages = quote_ages_ms(latest_quotes.values())
    return {
        "stocks": summarize(stock_samples),
        "option_chain": summarize(option_samples),
        "local_screen": summarize(screening_samples),
        "stock_quote_age_ms": {
            "median": round(statistics.median(ages), 1) if ages else None,
            "max": round(max(ages), 1) if ages else None,
        },
        "screened_contracts": [row.to_dict() for row in screened],
        "parameters": {
            "stocks": stocks,
            "underlying": underlying,
            "runs": runs,
            "warmups": warmups,
            "dte": [dte_min, dte_max],
            "strike_range": [strike_low, strike_high],
        },
    }

