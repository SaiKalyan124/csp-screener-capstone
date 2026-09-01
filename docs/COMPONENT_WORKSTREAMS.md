# Component architecture and development workstreams

The application is split around stable interfaces so each workstream can change its own implementation without reaching into another component.

```text
Browser UI
   |
HTTP transport (server.py)
   |
Application service (cache, scheduling, orchestration)
   +-------------------------+
   |                         |
Deterministic workflow    Research agent
   |                         |
Market-data provider      Retrieval / LLM / LangGraph
   |
Alpaca

All layers -> tracing/evaluation -> Arize
```

## Parallel development workstreams

| Owner | Scope | Primary paths | Interface to preserve |
|---|---|---|---|
| 1. Market data | Alpaca MCP/API adapters, normalization, latency | `src/csp_screener/providers/` | `latest_trade`, `option_chain`, `daily_bars` |
| 2. CSP ranking | Eligibility rules, scoring, contract selection | `src/csp_screener/iteration1.py`, `src/csp_screener/workflows/` | `IterationOneWorkflow.screen/options` |
| 3. Research agent | Intent routing, RAG, follow-ups, memory | `src/csp_screener/iteration2.py`, `src/csp_screener/agents/` | `ResearchAgent.ask` |
| 4. Observability/evals | Arize spans, datasets, regression metrics | `tests/`, tracing helpers | Trace names and evaluation fixtures |
| 5. App/API | Cache, scheduler, validation, deployment health | `src/csp_screener/services/`, `src/csp_screener/server.py` | `/api/screen`, `/api/options`, `/api/chat` |
| 6. Frontend | Dashboard, screener, profile and chat UX | `web/` | API response contracts |
| 7. QA/deployment | Integration tests, fixtures, hosting, runbooks | `tests/`, `docs/`, deployment config | Release checks |

## Dependency rules

1. The HTTP handler validates and serializes only; it does not rank contracts or call Alpaca directly.
2. The application service owns orchestration, cache lifetime and background refresh.
3. Workflows depend on provider interfaces, never on HTTP or UI code.
4. Providers normalize external data but contain no CSP eligibility or ranking policy.
5. The deterministic workflow remains usable without an LLM. The research agent consumes its results as grounded context.
6. Frontend changes should use existing API contracts or coordinate an explicit contract-version change.
7. Every workstream adds focused unit tests; cross-component behavior belongs in integration tests.

## Shared configuration

Runtime configuration is centralized in `src/csp_screener/config.py`. Secrets remain in `.env`; modules receive a `Settings` object and should not independently search the filesystem for credentials.

## Safe extension points

- Add Alpaca MCP by implementing the same provider methods and selecting the adapter in the composition root.
- Add a LangGraph workflow under `workflows/` without changing HTTP routes.
- Add durable profile or conversation memory behind a repository interface owned by the agent workstream.
- Add another cache or scheduler implementation behind `ApplicationService` without changing ranking logic.
