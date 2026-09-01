# CSP Screener — MCP-First Capstone Design

Status: proposed architecture  
Audience: instructors, developers, and demo reviewers  
Primary data integration: official Alpaca MCP Server  
Orchestration: LangGraph and LangChain  
Observability: Arize with OpenTelemetry and OpenInference

## 1. Executive summary

The CSP Screener helps a user identify liquid stocks that may be suitable for cash-secured-put research, inspect a bounded set of option contracts, and ask grounded questions about the results.

The design separates three responsibilities:

1. **Alpaca MCP provides facts.** Stock bars, quotes, snapshots, option chains, Greeks, implied volatility, news, market clock, and asset metadata arrive through typed MCP tools.
2. **Deterministic code calculates and ranks.** Eligibility cuts, returns, volatility, liquidity, collateral, yields, and scores are tested Python functions. The LLM never calculates or changes these values.
3. **The agent routes and explains.** LangChain and LangGraph let Kezzy interpret intent, select a bounded read-only tool or workflow, and explain stored results. The agent cannot trade.

Arize captures the complete trace so the project can demonstrate which MCP tools ran, their latency, what deterministic nodes produced, how many model tokens were used, and whether the response remained grounded.

## 2. Problem statement

Finding CSP candidates requires combining stock liquidity and history, a stable ranking method, option-chain availability, contract liquidity and Greeks, and user constraints such as buying power and preferred DTE.

A language model is useful for intent recognition, routing, follow-up questions, and explanation. It is not the right component for numerical screening or ranking.

## 3. Goals

### User goals

- Run one on-demand market screen.
- See the top 10 CSP-eligible stocks on Dashboard.
- Inspect any ticker in Screener.
- See five OTM cash-secured puts and five OTM covered calls for one 20–35 DTE expiration.
- Understand why a stock or contract appears.
- Ask Kezzy questions grounded in the latest run.

### Engineering goals

- Replace application-level Alpaca REST/SDK calls with official Alpaca MCP tools.
- Keep market calculations deterministic and unit-tested.
- Make each workflow observable in Arize.
- Bound tool access, latency, cost, and autonomy.
- Preserve a clear path from prototype to multi-user application.

### Non-goals

- Live trading or autonomous order placement.
- Personalized investment advice.
- Guaranteed profitability.
- High-frequency trading.
- LLM-generated rankings or calculations.
- Multi-agent architecture in early iterations.

## 4. Architecture decisions

| Area | Choice | Reason |
|---|---|---|
| Alpaca access | Official Alpaca MCP Server over stdio | Standard typed tool boundary |
| Enabled toolsets | assets, stock-data, options-data, news | Read-only capabilities needed for the capstone |
| Disabled toolsets | trading, account, watchlists initially | Least privilege |
| Ranking | Deterministic Python | Repeatable and testable |
| Workflow runtime | LangGraph | Explicit state, nodes, edges, retries, and persistence path |
| Agent framework | LangChain create_agent | Bounded conversational tool routing |
| MCP adapter | langchain-mcp-adapters | Converts MCP tools into LangChain tools |
| Observability | Arize and OpenTelemetry/OpenInference | Tool, workflow, LLM, error, latency, and eval traces |
| Persistence | Session state first; database later | Avoid premature infrastructure |

The official Alpaca server exposes market-data tools including stock bars, snapshots, option chains, Greeks, news, assets, and market clock. It supports toolset filtering through ALPACA_TOOLSETS. The project omits trading tools entirely. See the [official Alpaca MCP documentation](https://docs.alpaca.markets/us/docs/alpaca-mcp-server).

## 5. System context

~~~mermaid
flowchart LR
    U[User] --> UI[CSP Web App]
    UI --> API[Application Backend]
    API --> G[LangGraph Workflows]
    API --> K[Kezzy LangChain Agent]
    G --> D[Deterministic Screen and Rank]
    G --> M[MCP Client Adapter]
    K -->|bounded tools| M
    K --> LLM[OpenAI model]
    M --> A[Official Alpaca MCP Server]
    A --> ALP[Alpaca Market Data]
    D --> S[(Screen State and Cache)]
    G --> S
    K --> S
    API -. telemetry .-> AR[Arize]
    G -. spans .-> AR
    K -. spans .-> AR
    M -. tool spans .-> AR
~~~

## 6. Trust boundaries

### Deterministic numerical layer

- Symbol validation
- Returns, dollar volume, and realized volatility
- Stock eligibility and ranking
- OCC symbol parsing, DTE, and moneyness
- Bid/ask midpoint and spread
- Collateral, premium, yield, annualization, and breakeven
- Contract filtering, ordering, and limits

### External provider layer

Alpaca MCP output is external data. Validate it before inserting it into workflow state. Missing, stale, malformed, entitlement-limited, or crossed quotes must be visible rather than silently repaired.

### Probabilistic agent layer

The LLM may classify intent, choose from an allowlist, ask a clarifying question, summarize evidence, and explain deterministic results.

The LLM may not invent market values, alter formulas, silently substitute missing data, call trading tools, or claim safety or profitability.

## 7. Alpaca MCP integration

### 7.1 Process configuration

The application launches the MCP server as a child process:

~~~json
{
  "alpaca": {
    "transport": "stdio",
    "command": "uvx",
    "args": ["alpaca-mcp-server"],
    "env": {
      "ALPACA_API_KEY": "from process environment",
      "ALPACA_SECRET_KEY": "from process environment",
      "ALPACA_PAPER_TRADE": "true",
      "ALPACA_TOOLSETS": "assets,stock-data,options-data,news"
    }
  }
}
~~~

Secrets come from the operating environment or hosting secret store. They are never committed, rendered in the browser, placed in prompts, or recorded in Arize.

### 7.2 Client lifecycle

Use MultiServerMCPClient from langchain-mcp-adapters. LangChain documents that it is stateless by default and creates a fresh MCP session per call. Use an explicit session for one screen run so subprocess and connection lifecycle are controlled. See [LangChain MCP integration](https://docs.langchain.com/oss/python/langchain/mcp).

### 7.3 Tool map

| Need | Alpaca MCP tool | Caller |
|---|---|---|
| Validate symbol | get_asset | Deterministic workflow |
| Historical price and volume | get_stock_bars | Deterministic workflow |
| Current quote context | get_stock_snapshot | Deterministic workflow |
| Market open/close | get_clock | Workflow |
| Option universe | get_option_chain | Deterministic workflow |
| Contract Greeks if needed | get_option_snapshot | Deterministic workflow |
| Recent news | get_news | Iteration 2 research node or Kezzy |

### 7.4 Why MCP improves the design

- Standard tool contracts separate workflow code from provider SDK calls.
- Deterministic workflows and the agent can share the same provider boundary.
- Tool name, arguments, output, errors, and latency can be traced consistently.
- Toolset filtering provides least privilege.
- The capstone demonstrates MCP without making the LLM responsible for bulk work.

MCP does not remove provider rate limits, entitlements, or latency. It changes the integration boundary. OPRA versus indicative access still determines option-data freshness and fidelity.

## 8. Deterministic stock ranking

### Universe

Iteration 1 uses a versioned static list of liquid US equities. The production candidate is the NASDAQ-100 plus approved additions. Record the exact universe version on every run.

### Hard eligibility cuts

Exclude a stock when:

- it is inactive or not optionable;
- fewer than 45 valid daily bars are available;
- its price is below $10;
- average dollar volume is below $50M;
- three-month return is below -25%;
- required data is missing or stale.

### Explainable score

~~~text
stock_score =
    0.40 × liquidity_score
  + 0.35 × momentum_score
  + 0.25 × realized_volatility_score
~~~

The formula is configuration, not prompt text. Persist each component so UI and chat explanations use exact values.

The workflow returns 12 qualified names. Dashboard displays the top 10. Screener does not repeat the ranking.

## 9. Deterministic contract screen

For one selected ticker:

1. Validate the asset.
2. Fetch the current stock snapshot.
3. Request an option chain restricted to 20–35 DTE and a bounded strike range.
4. Choose the nearest eligible expiration with sufficient quotes.
5. Keep OTM puts below spot and OTM calls above spot.
6. Apply quote-quality and liquidity cuts.
7. Calculate deterministic metrics.
8. Return five CSP puts and five covered calls.

| Rule | CSP puts | Covered calls |
|---|---|---|
| DTE | 20–35 | 20–35 |
| Moneyness | OTM | OTM |
| Bid | greater than zero | greater than zero |
| Ask | greater than bid | greater than bid |
| Spread | configurable, start at 20% maximum | same |
| Delta target | about -0.15 to -0.35 | about +0.15 to +0.35 |
| Volume/open interest | apply when available | apply when available |

### CSP calculations

~~~text
cash_collateral       = strike × 100
premium_credit        = midpoint × 100
premium_yield_pct     = premium_credit / cash_collateral × 100
annualized_yield_pct  = premium_yield_pct × 365 / DTE
breakeven             = strike - midpoint
downside_buffer_pct   = (spot - breakeven) / spot × 100
~~~

Covered calls are presented for comparison; the primary capstone strategy remains CSP.

## 10. LangGraph workflow design

LangGraph distinguishes fixed workflows from dynamic agents. Screening is fixed because its order and rules are known. Kezzy is bounded and dynamic because questions vary. See [LangGraph workflows and agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents).

### On-demand stock screen

~~~mermaid
flowchart LR
    A[Start] --> B[Load versioned universe]
    B --> C[Open Alpaca MCP session]
    C --> D[Fetch stock bars]
    D --> E[Validate and normalize]
    E --> F[Hard eligibility cuts]
    F --> G[Deterministic score]
    G --> H[Sort and keep 12]
    H --> I[Save latest screen]
    I --> J[Publish top 10]
    J --> K[End]
~~~

No LLM call occurs in this graph.

### Ticker option screen

~~~mermaid
flowchart LR
    A[Validate ticker] --> B[Get asset]
    B --> C[Get stock snapshot]
    C --> D[Get option chain]
    D --> E[Validate quotes and Greeks]
    E --> F[Calculate CSP and CC metrics]
    F --> G[Select 5 puts and 5 calls]
    G --> H[Return typed response]
~~~

No LLM call occurs in this graph.

### Kezzy graph

~~~mermaid
flowchart TD
    A[User message] --> B[Intent router]
    B -->|ranking question| C[Read latest screen]
    B -->|ticker fact| D[Allowlisted MCP tool]
    B -->|option comparison| E[Run ticker workflow]
    B -->|news question| F[Get Alpaca news]
    B -->|trading or unsupported| G[Refuse or clarify]
    C --> H[Grounded response]
    D --> H
    E --> H
    F --> H
    H --> I[Response validator]
~~~

### Shared state

~~~python
class ScreenState(TypedDict):
    run_id: str
    universe_version: str
    started_at: str
    profile: dict
    market_clock: dict | None
    eligible_candidates: list[dict]
    ranked_candidates: list[dict]
    selected_ticker: str | None
    selected_contracts: list[dict]
    warnings: list[str]
    errors: list[dict]
    timings_ms: dict[str, int]
~~~

Do not copy large raw provider payloads through every graph transition. Pass normalized models or data references.

## 11. LangChain responsibilities

Use LangChain for:

- loading MCP tools;
- creating the Kezzy agent;
- structured model output;
- prompt and response middleware;
- tool interceptors and runtime context.

Do not use LangChain for ranking, option calculations, provider validation, or caching.

### Required tool interceptors

- allowlist enforcement;
- argument and symbol-count validation;
- timeout and retry policy;
- session rate limiting;
- trace metadata;
- output normalization and truncation;
- secret and sensitive-field redaction.

## 12. Arize observability

Arize’s LangChain integration uses OpenInference instrumentation on OpenTelemetry and captures model, chain, and tool spans. See [Arize LangChain tracing](https://arize.com/docs/ax/observe/tracing-integrations-auto/langchain) and [Arize tracing concepts](https://arize.com/docs/ax/observe/tracing/spans).

### Trace hierarchy

~~~text
screen.run
├── universe.load
├── mcp.session.open
├── mcp.get_stock_bars
├── data.validate
├── eligibility.filter
├── ranking.calculate
├── state.save
└── response.render

kezzy.turn
├── intent.route
├── state.retrieve or mcp.tool
├── llm.generate
├── response.validate
└── response.render
~~~

### Required trace attributes

- project.name = csp-screener-capstone
- app.iteration and workflow.name
- run.id and pseudonymous session.id
- universe.version and universe.count
- eligible.count and candidate.count
- ticker when applicable
- mcp.server and mcp.tool.name
- mcp.tool.success and retry.count
- market_data.feed and market_data.age_ms
- cache.hit and latency.ms
- model.name and prompt.version
- input/output tokens
- validation.result

### Never trace

- Alpaca or OpenAI keys;
- authorization headers;
- environment variables;
- account identifiers;
- holdings or buying power in early iterations;
- complete option-chain payloads;
- raw chat content when privacy mode is enabled.

### Arize dashboards

1. Screen latency and p95.
2. MCP tool latency, failure, and retry rate.
3. Cache hit rate.
4. Candidate-count drift.
5. Missing/stale data frequency.
6. Kezzy tool-choice accuracy.
7. Unsupported numerical claim rate.
8. Token usage and cost per chat turn.

## 13. Evaluation plan

### Deterministic unit tests

- OCC parsing and DTE boundaries.
- OTM classification.
- Collateral, breakeven, yield, and annualization.
- Missing/crossed quote rejection.
- Spread calculation.
- Stock cuts and score boundaries.
- Stable tie-breaking.

### MCP contract tests

Use recorded and redacted responses:

- expected allowlisted tools are discoverable;
- optional fields normalize safely;
- timeouts and rate limits map to safe errors;
- trading tools are absent;
- schema changes fail visibly.

### Workflow golden cases

- A valid liquid ticker returns one expiration and ten contracts.
- An invalid symbol fails before the chain request.
- Insufficient contracts produce a clear empty state.
- Indicative/delayed data produces a visible warning.
- Dashboard displays at most ten candidates.
- Screener does not duplicate Dashboard ranking.

### Agent evaluation set

Create 30–50 prompts covering ranking explanation, quotes, contract comparison, news, profile, unsupported fundamentals, trading requests, prompt injection, missing data, and follow-ups.

Score correct route, correct tool, unnecessary tools, grounded claims, trading refusal, uncertainty, and concise response.

### Quality gates

- MCP success rate at least 98%, excluding provider outages.
- Zero trading tool calls.
- Zero secret leakage.
- Numerical claims always trace to state or MCP output.
- Dashboard p95 target at most 3 seconds.
- Option screen p95 target at most 2 seconds.
- Kezzy p95 target at most 6 seconds.
- Agent routing at least 90% on the golden set.

## 14. Caching and rate limits

- Cache daily bars by symbol and trading date.
- Cache the latest completed ranking for the day/session.
- Cache chains briefly by ticker, DTE range, feed, and retrieval minute.
- Never cache provider errors as successful empty results.
- Use bounded concurrency.
- Retry only transient errors with exponential backoff.
- Record cache and retry behavior in Arize.

## 15. Failure behavior

| Failure | User experience | System behavior |
|---|---|---|
| MCP server unavailable | Market-data service unavailable | One reconnect attempt |
| Authentication rejected | Safe configuration error | No retry loop |
| Rate limited | Retry-later message | Backoff and trace |
| Missing stock bars | Candidate omitted with warning | Continue universe |
| No eligible expiry | Clear empty state | Never relax DTE silently |
| Indicative feed | Visible feed badge | Continue if permitted |
| LLM unavailable | Dashboard and Screener remain available | Disable Kezzy only |
| Arize unavailable | App remains available | Buffer or drop telemetry safely |

## 16. Security safeguards

- Enable only read-only Alpaca toolsets.
- Never load trading.
- Keep paper mode true even though trading is absent.
- Store credentials only in environment or hosting secrets.
- Validate symbols and numeric bounds.
- Limit universe size and MCP arguments.
- Set timeouts on every tool.
- Redact before tracing.
- Treat news/provider text as data, never as instructions.
- Keep calculations outside the model.
- Label output as educational research, not financial advice.
- Require a separate architecture review before paper-order functionality.

## 17. Typed data contracts

### Candidate

~~~json
{
  "symbol": "AAPL",
  "price": 316.85,
  "return_3m_pct": 0.5,
  "realized_vol_pct": 31.5,
  "avg_dollar_volume_m": 6210.4,
  "score_components": {
    "liquidity": 100,
    "momentum": 76,
    "realized_volatility": 92
  },
  "score": 90,
  "eligible": true,
  "reason_codes": ["LIQUID", "MOMENTUM_ACCEPTABLE", "VOL_IN_RANGE"]
}
~~~

### Contract

~~~json
{
  "symbol": "AAPL260925P00305000",
  "strategy": "cash_secured_put",
  "expiration": "2026-09-25",
  "dte": 24,
  "strike": 305.0,
  "spot": 317.14,
  "bid": 4.25,
  "ask": 4.55,
  "midpoint": 4.40,
  "spread_pct": 6.82,
  "delta": -0.28,
  "implied_volatility": 0.31,
  "cash_collateral": 30500,
  "premium_credit": 440,
  "premium_yield_pct": 1.44,
  "annualized_yield_pct": 21.9,
  "breakeven": 300.60,
  "feed": "indicative",
  "as_of": "2026-09-01T15:30:00Z"
}
~~~

## 18. UX blueprint

### Dashboard

- Top 10 CSP-eligible stocks only.
- Screen time, feed, and MCP latency.
- Score and deterministic reason.
- Candidate click opens Screener.
- Refresh runs the fixed workflow.

### Screener

- One ticker input.
- Current stock price and timestamp.
- One 20–35 DTE expiration.
- Five CSP puts and five covered calls.
- Readable label plus OCC symbol.
- Collateral, premium, yield, delta, IV, and spread.
- Clear empty, error, and feed states.

### Kezzy

- Static shell in Iteration 1.
- Grounded session chat in Iteration 2.
- Uses latest ranking, selected chain, profile, and optional news.
- Shows when it used a tool.
- Does not rerun the universe for ordinary chat.

## 19. Delivery iterations

### Iteration 0 — Current prototype

- Direct Alpaca SDK calls.
- Deterministic 24-symbol ranking.
- Dashboard top 10.
- Ticker puts/calls screen.
- Static Kezzy.

Purpose: validate UX, calculations, and latency.

### Iteration 1 — MCP migration

- Add official Alpaca MCP Server.
- Enable assets, stock-data, options-data, and news only.
- Replace application SDK calls with an MCP gateway.
- Preserve deterministic domain functions.
- Add typed normalization, timeouts, caching, and Arize spans.
- Keep Kezzy static.

Exit criteria:

- Existing tests pass with recorded MCP fixtures.
- Dashboard and Screener use MCP only.
- Trading tools are not discoverable.
- Arize shows workflow and MCP spans.

### Iteration 2 — Bounded Kezzy

- Add LangChain agent.
- Add LangGraph intent router.
- Give read access to latest state.
- Allow selected market-data/news tools.
- Add structured response validation.
- Add approximately eight turns of session memory.
- Add Arize evaluators and a golden prompt set.

Exit criteria:

- Routing meets the target.
- Numerical claims are grounded.
- Chat does not rerun the full screen unnecessarily.
- No trading path exists.

### Iteration 3 — Persistence and automation

- User profiles and buying-power constraints.
- Persistent watchlist, history, and selected contracts.
- Scheduled pre-market/nightly screen.
- Digest or notification workflow.
- Long-term quality and drift monitoring.

## 20. Proposed repository structure

~~~text
src/csp_screener/
├── api/
├── mcp/
│   ├── client.py
│   ├── gateway.py
│   ├── interceptors.py
│   └── normalization.py
├── workflows/
│   ├── screen_graph.py
│   ├── option_graph.py
│   └── kezzy_graph.py
├── domain/
│   ├── eligibility.py
│   ├── ranking.py
│   ├── options.py
│   └── models.py
├── agents/
│   ├── kezzy.py
│   ├── prompts.py
│   └── response_validation.py
├── observability/
│   ├── tracing.py
│   └── redaction.py
├── storage/
└── config.py

tests/
├── unit/
├── mcp_contract/
├── workflow/
├── agent_evals/
└── fixtures/
~~~

## 21. Demo narrative

1. Dashboard starts a fixed LangGraph workflow.
2. The workflow calls Alpaca through the official MCP server.
3. Python applies hard cuts and ranking; no LLM is involved.
4. Top 10 render with explainable values.
5. Selecting a ticker calls the option-chain MCP tool.
6. Python selects five OTM CSP puts and five OTM covered calls.
7. Kezzy explains a result with one bounded model call.
8. Arize shows the trace, timing, tools, and evaluation.
9. Trading is impossible because the toolset is absent.

## 22. Open decisions

- NASDAQ-100 only or a broader approved universe.
- Final liquidity, spread, and delta thresholds.
- Whether indicative options data is sufficient for the demo.
- Whether Alpaca news fully replaces Tavily.
- Arize AX cloud versus Phoenix/local.
- Database choice for Iteration 3.
- Hosting model for the MCP child process.

## 23. Recommended next action

Treat Iteration 1 as an adapter migration, not a rewrite:

1. Introduce AlpacaMCPGateway.
2. Record normalized fixtures for required tools.
3. Route current screen services through the gateway.
4. Preserve existing ranking and option-selection functions.
5. Instrument nodes and MCP calls with Arize.
6. Compare MCP latency and output with the direct prototype.

This produces a clear capstone story: direct prototype, standardized MCP integration, bounded agent, then an observable and evaluated platform.

## 24. Primary references

- [Alpaca Trading MCP Server](https://docs.alpaca.markets/us/docs/alpaca-mcp-server)
- [LangChain MCP integration](https://docs.langchain.com/oss/python/langchain/mcp)
- [LangGraph workflows and agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents)
- [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)
- [Arize LangChain tracing](https://arize.com/docs/ax/observe/tracing-integrations-auto/langchain)
- [Arize tracing concepts](https://arize.com/docs/ax/observe/tracing/spans)

## 25. Architecture and sequence diagrams

The companion [Architecture and Sequence Diagrams](ARCHITECTURE_AND_SEQUENCE_DIAGRAMS.md) adds the high-level component view, scheduled refresh design, freshness rules, user-perspective sequences, refresh state machine, and deployment view.
