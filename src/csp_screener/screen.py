from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from math import log10, sqrt
from statistics import pstdev
from typing import Any, Iterable


@dataclass(frozen=True)
class ScreenedContract:
    symbol: str
    bid: float
    ask: float
    midpoint: float
    spread_pct: float
    implied_volatility: float | None
    delta: float | None
    quote_age_ms: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StockCandidate:
    symbol: str
    price: float
    return_3m_pct: float
    realized_vol_pct: float
    avg_dollar_volume_m: float
    score: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_occ_symbol(symbol: str) -> tuple[str, date, str, float]:
    """Parse an OCC symbol such as AAPL260116C00200000."""
    tail = symbol[-15:]
    expiry = datetime.strptime(tail[:6], "%y%m%d").date()
    return symbol[:-15], expiry, tail[6], int(tail[7:]) / 1000


def _number(value: Any) -> float | None:
    return None if value is None else float(value)


def screen_chain(
    snapshots: dict[str, Any],
    *,
    max_spread_pct: float = 20.0,
    min_bid: float = 0.05,
    limit: int = 25,
    now: datetime | None = None,
) -> list[ScreenedContract]:
    now = now or datetime.now(timezone.utc)
    results: list[ScreenedContract] = []
    for symbol, snapshot in snapshots.items():
        quote = getattr(snapshot, "latest_quote", None)
        if quote is None:
            continue
        bid = _number(getattr(quote, "bid_price", None))
        ask = _number(getattr(quote, "ask_price", None))
        if bid is None or ask is None or bid < min_bid or ask <= bid:
            continue
        midpoint = (bid + ask) / 2
        spread_pct = (ask - bid) / midpoint * 100
        if spread_pct > max_spread_pct:
            continue
        stamp = getattr(quote, "timestamp", None)
        age_ms = (now - stamp).total_seconds() * 1000 if stamp else None
        greeks = getattr(snapshot, "greeks", None)
        results.append(
            ScreenedContract(
                symbol=symbol,
                bid=bid,
                ask=ask,
                midpoint=round(midpoint, 4),
                spread_pct=round(spread_pct, 3),
                implied_volatility=_number(getattr(snapshot, "implied_volatility", None)),
                delta=_number(getattr(greeks, "delta", None)) if greeks else None,
                quote_age_ms=round(age_ms, 1) if age_ms is not None else None,
            )
        )
    return sorted(results, key=lambda row: (row.spread_pct, -(row.bid)))[:limit]


def quote_ages_ms(quotes: Iterable[Any], now: datetime | None = None) -> list[float]:
    now = now or datetime.now(timezone.utc)
    return [
        (now - quote.timestamp).total_seconds() * 1000
        for quote in quotes
        if getattr(quote, "timestamp", None) is not None
    ]


def rank_stock_candidates(
    bars_by_symbol: dict[str, Iterable[Any]], *, limit: int = 12
) -> list[StockCandidate]:
    """Rank liquid stocks for covered-call research using market data only."""
    candidates: list[StockCandidate] = []
    for symbol, source_bars in bars_by_symbol.items():
        bars = list(source_bars)
        if len(bars) < 45:
            continue
        closes = [float(bar.close) for bar in bars if float(bar.close) > 0]
        if len(closes) < 45:
            continue
        recent = bars[-63:] if len(bars) >= 63 else bars
        start_price = float(recent[0].close)
        price = float(recent[-1].close)
        return_3m = (price / start_price - 1) * 100
        dollar_volumes = [
            float(bar.close) * float(getattr(bar, "volume", 0) or 0)
            for bar in recent
        ]
        avg_dollar_volume = sum(dollar_volumes) / len(dollar_volumes)
        daily_returns = [
            closes[index] / closes[index - 1] - 1
            for index in range(1, len(closes))
        ]
        realized_vol = pstdev(daily_returns[-62:]) * sqrt(252) * 100

        if price < 10 or avg_dollar_volume < 50_000_000 or return_3m < -25:
            continue

        liquidity_score = min(100, max(0, (log10(avg_dollar_volume) - 7.7) / 2 * 100))
        momentum_score = max(0, 100 - abs(return_3m - 8) * 3.2)
        volatility_score = max(0, 100 - abs(realized_vol - 35) * 2.4)
        score = round(
            liquidity_score * 0.40
            + momentum_score * 0.35
            + volatility_score * 0.25
        )

        if return_3m >= 0:
            direction = f"{return_3m:.1f}% three-month gain"
        else:
            direction = f"{abs(return_3m):.1f}% three-month pullback"
        reason = (
            f"Liquid shares, {direction}, and {realized_vol:.1f}% realized volatility "
            "make this suitable for cash-secured-put review."
        )
        candidates.append(
            StockCandidate(
                symbol=symbol,
                price=round(price, 2),
                return_3m_pct=round(return_3m, 1),
                realized_vol_pct=round(realized_vol, 1),
                avg_dollar_volume_m=round(avg_dollar_volume / 1_000_000, 1),
                score=score,
                reason=reason,
            )
        )
    return sorted(candidates, key=lambda row: (-row.score, row.symbol))[:limit]


def select_demo_calls(
    snapshots: dict[str, Any], spot: float, *, count: int = 5
) -> tuple[date, list[dict[str, Any]]]:
    """Return nearest five ITM and five OTM calls at one expiration."""
    grouped: dict[date, list[dict[str, Any]]] = {}
    for symbol, snapshot in snapshots.items():
        try:
            _, expiry, contract_type, strike = parse_occ_symbol(symbol)
        except (ValueError, IndexError):
            continue
        if contract_type != "C":
            continue
        quote = getattr(snapshot, "latest_quote", None)
        if quote is None:
            continue
        bid = _number(getattr(quote, "bid_price", None))
        ask = _number(getattr(quote, "ask_price", None))
        if bid is None or ask is None or bid < 0 or ask <= 0:
            continue
        greeks = getattr(snapshot, "greeks", None)
        row = {
            "symbol": symbol,
            "type": "Call",
            "strike": strike,
            "bid": bid,
            "ask": ask,
            "implied_volatility": _number(
                getattr(snapshot, "implied_volatility", None)
            ),
            "delta": _number(getattr(greeks, "delta", None)) if greeks else None,
        }
        grouped.setdefault(expiry, []).append(row)

    for expiry in sorted(grouped):
        rows = grouped[expiry]
        itm = sorted(
            (row for row in rows if row["strike"] < spot),
            key=lambda row: spot - row["strike"],
        )[:count]
        otm = sorted(
            (row for row in rows if row["strike"] > spot),
            key=lambda row: row["strike"] - spot,
        )[:count]
        if len(itm) == count and len(otm) == count:
            for moneyness, selected in (("ITM", itm), ("OTM", otm)):
                for row in selected:
                    row["moneyness"] = moneyness
                    row["distance_pct"] = round(
                        (row["strike"] - spot) / spot * 100, 2
                    )
            return expiry, itm + otm
    raise ValueError("No expiration has five quoted ITM and OTM call contracts")


def select_csp_and_covered_calls(
    snapshots: dict[str, Any],
    spot: float,
    *,
    count: int = 5,
    min_bid: float = 0.10,
    max_spread_pct: float = 20.0,
    min_abs_delta: float = 0.15,
    max_abs_delta: float = 0.40,
    target_abs_delta: float = 0.25,
) -> tuple[date, list[dict[str, Any]]]:
    """Return the highest-ranked eligible CSPs and covered calls.

    Distance from spot is descriptive only. Eligibility and ranking are based on
    quote quality, liquidity and the configured delta band.
    """
    grouped: dict[date, dict[str, list[dict[str, Any]]]] = {}
    for symbol, snapshot in snapshots.items():
        try:
            _, expiry, contract_type, strike = parse_occ_symbol(symbol)
        except (ValueError, IndexError):
            continue
        quote = getattr(snapshot, "latest_quote", None)
        if quote is None:
            continue
        bid = _number(getattr(quote, "bid_price", None))
        ask = _number(getattr(quote, "ask_price", None))
        if bid is None or ask is None or bid < min_bid or ask <= bid:
            continue
        midpoint = (bid + ask) / 2
        spread_pct = (ask - bid) / midpoint * 100
        if spread_pct > max_spread_pct:
            continue
        greeks = getattr(snapshot, "greeks", None)
        delta = _number(getattr(greeks, "delta", None)) if greeks else None
        if delta is None or not min_abs_delta <= abs(delta) <= max_abs_delta:
            continue
        premium_yield_pct = midpoint / strike * 100
        delta_fit = max(0.0, 1 - abs(abs(delta) - target_abs_delta) / 0.15)
        spread_fit = max(0.0, 1 - spread_pct / max_spread_pct)
        liquidity_fit = min(1.0, bid / 2.0)
        rank_score = round(
            (delta_fit * 0.50 + spread_fit * 0.30 + liquidity_fit * 0.20) * 100
        )
        row = {
            "symbol": symbol,
            "type": "Put" if contract_type == "P" else "Call",
            "strike": strike,
            "bid": bid,
            "ask": ask,
            "implied_volatility": _number(
                getattr(snapshot, "implied_volatility", None)
            ),
            "delta": delta,
            "distance_pct": round((strike - spot) / spot * 100, 2),
            "midpoint": round(midpoint, 4),
            "spread_pct": round(spread_pct, 2),
            "premium_yield_pct": round(premium_yield_pct, 2),
            "eligibility": "eligible",
            "rank_score": rank_score,
            "rank_reason": (
                f"Delta within {min_abs_delta:.2f}–{max_abs_delta:.2f}; "
                f"{spread_pct:.1f}% spread and ${bid:.2f} bid passed liquidity rules."
            ),
        }
        bucket = grouped.setdefault(expiry, {"P": [], "C": []})
        if contract_type in bucket:
            bucket[contract_type].append(row)

    for expiry in sorted(grouped):
        puts = sorted(
            (row for row in grouped[expiry]["P"] if row["strike"] < spot),
            key=lambda row: (-row["rank_score"], -row["premium_yield_pct"], row["strike"]),
        )[:count]
        calls = sorted(
            (row for row in grouped[expiry]["C"] if row["strike"] > spot),
            key=lambda row: (-row["rank_score"], -row["premium_yield_pct"], -row["strike"]),
        )[:count]
        if len(puts) == count and len(calls) == count:
            for row in puts:
                row["strategy"] = "Cash-secured put"
                row["moneyness"] = "OTM"
            for row in calls:
                row["strategy"] = "Covered call"
                row["moneyness"] = "OTM"
            return expiry, puts + calls
    raise ValueError(
        "No expiration has five eligible OTM puts and calls within the configured "
        "delta, bid, and spread rules"
    )


def select_quoted_contracts_for_expiration(
    snapshots: dict[str, Any],
    spot: float,
    expiration: date,
    *,
    count: int = 5,
    min_bid: float = 0.05,
    max_spread_pct: float = 50.0,
    target_abs_delta: float = 0.25,
) -> tuple[date, list[dict[str, Any]]]:
    """Return quoted puts and calls for one expiration without the 5+5 screen."""
    puts: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    for symbol, snapshot in snapshots.items():
        try:
            _, expiry, contract_type, strike = parse_occ_symbol(symbol)
        except (ValueError, IndexError):
            continue
        if expiry != expiration:
            continue
        quote = getattr(snapshot, "latest_quote", None)
        if quote is None:
            continue
        bid = _number(getattr(quote, "bid_price", None))
        ask = _number(getattr(quote, "ask_price", None))
        if bid is None or ask is None or bid < min_bid or ask <= bid:
            continue
        midpoint = (bid + ask) / 2
        spread_pct = (ask - bid) / midpoint * 100
        if spread_pct > max_spread_pct:
            continue
        greeks = getattr(snapshot, "greeks", None)
        delta = _number(getattr(greeks, "delta", None)) if greeks else None
        row = {
            "symbol": symbol,
            "type": "Put" if contract_type == "P" else "Call",
            "strike": strike,
            "bid": bid,
            "ask": ask,
            "implied_volatility": _number(
                getattr(snapshot, "implied_volatility", None)
            ),
            "delta": delta,
            "distance_pct": round((strike - spot) / spot * 100, 2),
            "midpoint": round(midpoint, 4),
            "spread_pct": round(spread_pct, 2),
            "premium_yield_pct": round(midpoint / strike * 100, 2),
            "eligibility": "quoted",
            "rank_score": round(
                max(0.0, 1 - abs(abs(delta or target_abs_delta) - target_abs_delta) / 0.25)
                * 100
            ),
            "rank_reason": f"Quoted {expiry.isoformat()} contract from Alpaca.",
        }
        if contract_type == "P":
            row["strategy"] = "Cash-secured put"
            row["moneyness"] = "OTM" if strike < spot else "ITM"
            puts.append(row)
        elif contract_type == "C":
            row["strategy"] = "Covered call"
            row["moneyness"] = "OTM" if strike > spot else "ITM"
            calls.append(row)

    def _rank(rows: list[dict[str, Any]], *, otm_first: bool) -> list[dict[str, Any]]:
        return sorted(
            rows,
            key=lambda row: (
                0 if (row["strike"] < spot if otm_first else row["strike"] > spot) else 1,
                -row["rank_score"],
                -row["premium_yield_pct"],
                row["strike"] if otm_first else -row["strike"],
            ),
        )[:count]

    otm_puts = [row for row in puts if row["strike"] < spot]
    selected = _rank(otm_puts or puts, otm_first=True) + _rank(calls, otm_first=False)
    if not selected:
        raise ValueError(f"No quoted option contracts for {expiration.isoformat()}")
    return expiration, selected
