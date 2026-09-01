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
4. Apply hard eligibility rules and score qualified symbols.
5. Publish the top ten with score components, reason codes, and timestamps.

## Ticker option workflow

1. Validate that the symbol is active and optionable.
2. Fetch its latest trade to establish spot price.
3. Fetch a bounded option chain for the configured DTE and strike window.
4. Validate quotes, Greeks, timestamps, and liquidity.
5. Calculate cash required, premium yield, break-even, distance from spot, and assignment exposure.
6. Return five CSP candidates and five covered-call candidates.

## Trust and failure rules

- The model never calculates or changes market values.
- Missing data remains missing; it is not silently invented or repaired.
- Entitlement-limited or stale feeds are visible in the response.
- Provider timeouts and retries are bounded.
- The provider exposes read-only market data and no trading capability.
