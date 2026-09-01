# Application API and UI

## Responsibility

The application service composes providers, workflows, caching, refresh scheduling, and the research agent. The HTTP layer validates and serializes requests; it contains no ranking or research policy.

## API contracts

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/api/screen` | Return the latest ranked dashboard snapshot |
| `GET` | `/api/screen?refresh=1` | Force a fresh deterministic screen |
| `GET` | `/api/options?symbol=MU` | Return ticker-specific option candidates |
| `POST` | `/api/chat` | Run grounded ticker or discovery research |

Responses include generated time, market-data time, workflow latency, cache status, source information, and visible warnings when available.

## Caching and refresh

- Cache hits must not wait behind an active provider refresh.
- Concurrent refresh misses are coalesced.
- Background refresh uses the same deterministic workflow as manual refresh.
- A failed refresh retains the last successful snapshot.
- Durable storage can replace the in-memory cache without changing API contracts.

## UI responsibilities

- Dashboard: top ten CSP-eligible stocks, scoring context, freshness, and refresh status.
- Screener: one ticker, readable contracts, five CSPs, five covered calls, and calculation details.
- Research panel: questions, citations, risk/uncertainty, and candidate cards that update the screener.
- Profile: budget, risk, timeline, sectors, and strategy constraints in Iteration 3.

## Definition of done

- Desktop and mobile flows pass browser tests.
- Loading, empty, stale, partial, and provider-error states are understandable.
- Agent-selected tickers update the visual screener correctly.
- Accessibility labels, keyboard navigation, contrast, and responsive layouts are verified.
