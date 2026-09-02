# Market data and screening

## Responsibility

This component obtains normalized stock and option data, applies deterministic eligibility rules, and returns reproducible CSP rankings and ticker-specific contracts.

## Interfaces

```python
latest_trade(symbol)
daily_bars(symbols, start)
option_chain(symbol, expiration_gte, expiration_lte, strike_gte, strike_lte)
```

The current adapter uses Alpaca's SDK. An Alpaca MCP implementation should satisfy the same provider contract so workflows do not depend on the transport.

## Dashboard workflow

1. Request approximately 120 days of daily bars for the configured universe in one batch.
2. Reject missing, stale, or insufficient histories.
3. Calculate liquidity, three-month momentum, and realized volatility.
4. Apply hard stock-level eligibility rules and score the qualified pool.
5. Fetch bounded option chains for that pool and require five eligible CSPs plus five eligible covered calls under the same rules used by the ticker screener.
6. Exclude symbols that lack sufficient eligible contracts; cache validated chains so dashboard clicks use the same snapshot.
7. Publish up to ten fully eligible symbols with score components, contract counts, reason codes, and timestamps.
8. Pass only that eligible shortlist to the bounded research classifier; the model cannot admit rejected symbols or change scores.

## Ticker option workflow

1. Validate that the symbol is active and optionable.
2. Fetch its latest trade to establish spot price.
3. Fetch a bounded option chain for the configured DTE and strike window.
4. Validate quotes, Greeks, timestamps, and liquidity.
5. Apply hard contract rules: 20–35 DTE, OTM strategy direction, bid at least $0.10, spread at most 20%, and absolute delta from 0.15 to 0.40.
6. Rank eligible contracts using 50% target-delta fit, 30% spread quality, and 20% bid liquidity.
7. Calculate cash required, premium yield, break-even, distance from spot, and assignment exposure.
8. Return the five highest-ranked eligible CSPs and covered calls. Distance from spot is descriptive and is not the selector.

## Trust and failure rules

- The model never calculates or changes market values.
- Missing data remains missing; it is not silently invented or repaired.
- Entitlement-limited or stale feeds are visible in the response.
- Provider timeouts and retries are bounded.
- The provider exposes read-only market data and no trading capability.
