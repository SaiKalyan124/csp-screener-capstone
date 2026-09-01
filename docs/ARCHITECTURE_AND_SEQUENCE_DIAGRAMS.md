# CSP Screener — Architecture and Sequence Diagrams

Companion to [MCP_FIRST_CAPSTONE_DESIGN.md](MCP_FIRST_CAPSTONE_DESIGN.md)

## 1. High-level architecture

~~~mermaid
flowchart LR
    subgraph Client
        U[User]
        WEB[Dashboard · Screener · Kezzy]
    end

    subgraph Application
        API[FastAPI Backend]
        LG[LangGraph Runtime]
        RANK[Deterministic Rank Engine]
        OPT[Deterministic Option Engine]
        AGENT[LangChain Kezzy Agent]
        CACHE[(Dashboard Snapshot Cache)]
        DB[(Profiles · History · Watchlists)]
    end

    subgraph Integration
        MCPCLIENT[LangChain MCP Adapter]
        ALPACAMCP[Official Alpaca MCP Server]
    end

    subgraph External
        ALPACA[Alpaca Market Data]
        LLM[OpenAI Model]
        ARIZE[Arize Observability]
    end

    subgraph Automation
        CRON[Scheduler / Cron]
        LOCK[Distributed Run Lock]
    end

    U --> WEB
    WEB --> API
    API --> CACHE
    API --> LG
    LG --> RANK
    LG --> OPT
    LG --> MCPCLIENT
    API --> AGENT
    AGENT --> LLM
    AGENT --> MCPCLIENT
    AGENT --> CACHE
    MCPCLIENT --> ALPACAMCP
    ALPACAMCP --> ALPACA
    RANK --> CACHE
    OPT --> CACHE
    API --> DB
    AGENT --> DB
    CRON --> LOCK
    LOCK --> LG
    API -. traces .-> ARIZE
    LG -. traces .-> ARIZE
    AGENT -. traces .-> ARIZE
    MCPCLIENT -. tool spans .-> ARIZE
~~~

### Primary design rule

The scheduler, user-triggered screen, and API reuse the same LangGraph workflow and deterministic ranker. Cron does not call Kezzy and does not invoke an LLM.

## 2. Component responsibilities

| Component | Responsibility | Must not do |
|---|---|---|
| Web UI | Display snapshots, accept ticker, host chat | Calculate finance metrics |
| FastAPI backend | Authenticate, route, validate, serve cached results | Call provider SDK directly |
| Scheduler | Trigger refresh at configured market times | Run overlapping jobs |
| Run lock | Enforce one active refresh per universe/profile | Hold a lock after failure |
| LangGraph screen workflow | Orchestrate MCP fetch, validation, ranking, publishing | Ask an LLM to rank |
| Alpaca MCP gateway | Start/manage MCP session, call allowlisted tools, normalize output | Expose trading tools |
| Rank engine | Cuts, score components, sorting, reason codes | Use prompt text |
| Option engine | DTE, moneyness, spread, delta, yield, collateral | Invent missing fields |
| Snapshot cache | Serve last successful immutable Dashboard run | Expose partial runs |
| Database | Profiles, history, watchlists, run metadata | Store provider secrets |
| Kezzy agent | Route questions and explain evidence | Trade or recalculate scores |
| Arize | Trace tools, workflows, LLM, latency, errors, evals | Receive secrets |

## 3. Freshness architecture

### Refresh policy

Use two scheduled jobs:

1. **Pre-market refresh:** approximately 30 minutes before market open. Builds an initial ranking from the most recently completed daily bars and current pre-market context when available.
2. **Market-hours refresh:** every 15 minutes while the market is open. Refreshes snapshots and recalculates the ranking.

Optional:

- One after-close run after daily bars settle.
- A manual refresh button with a per-user cooldown.

Do not run every minute. The strategy uses daily history and 20–35 DTE options, so a 15-minute Dashboard cadence is a reasonable initial tradeoff between freshness and rate limits.

### Snapshot metadata

Every published Dashboard snapshot contains:

- run ID;
- started and completed timestamps;
- market clock status;
- provider feed;
- universe version;
- source-data timestamps;
- candidate count;
- ranking version;
- next scheduled refresh;
- stale-after timestamp;
- warnings and excluded-symbol counts.

### Freshness states

| State | Rule | UI |
|---|---|---|
| Fresh | Age less than 20 minutes during market hours | Green “Updated N min ago” |
| Aging | 20–45 minutes during market hours | Amber warning |
| Stale | More than 45 minutes during market hours | Red warning and manual retry |
| Closed market | Latest successful after-close/pre-market snapshot | “Market closed” badge |
| No snapshot | No successful run exists | Empty state with retry |

The UI must show the age of the source data, not only the age of the HTTP response.

## 4. Scheduled dashboard refresh sequence

~~~mermaid
sequenceDiagram
    autonumber
    participant Cron as Scheduler/Cron
    participant Clock as Market Clock Policy
    participant Lock as Distributed Run Lock
    participant Graph as LangGraph Screen Workflow
    participant MCP as Alpaca MCP Gateway
    participant Alpaca as Alpaca MCP Server
    participant Rank as Deterministic Rank Engine
    participant Cache as Snapshot Cache
    participant History as Run History
    participant Arize as Arize

    Cron->>Clock: Should refresh now?
    Clock-->>Cron: Yes · market open
    Cron->>Lock: Acquire screen:universe-version

    alt Another refresh is active
        Lock-->>Cron: Lock unavailable
        Cron->>Arize: Record skipped duplicate
    else Lock acquired
        Lock-->>Cron: Lease + run ID
        Cron->>Graph: Start scheduled screen(run ID)
        Graph->>Arize: Start screen.run trace
        Graph->>MCP: Open read-only MCP session
        MCP->>Alpaca: get_clock
        Alpaca-->>MCP: Market state
        MCP->>Alpaca: get_stock_bars(symbol batch)
        Alpaca-->>MCP: OHLCV data
        MCP-->>Graph: Normalized bars + timestamps
        Graph->>Graph: Validate data and apply hard cuts
        Graph->>Rank: Calculate components and score
        Rank-->>Graph: Ranked 12 + reason codes
        Graph->>Cache: Publish immutable top-10 snapshot
        Cache-->>Graph: Snapshot version
        Graph->>History: Save run metadata and diagnostics
        Graph->>Arize: End trace with counts and timing
        Graph-->>Cron: Success
        Cron->>Lock: Release lease
    end
~~~

### Atomic publishing rule

The workflow writes to a temporary run record first. The Dashboard pointer moves to the new snapshot only after validation and ranking complete. A failed run never replaces the last successful snapshot.

## 5. User opens Dashboard

~~~mermaid
sequenceDiagram
    autonumber
    actor User
    participant UI as Web Dashboard
    participant API as FastAPI
    participant Cache as Snapshot Cache
    participant Clock as Freshness Policy
    participant Cron as Scheduler Status

    User->>UI: Open Dashboard
    UI->>API: GET /dashboard/latest
    API->>Cache: Read latest successful snapshot
    Cache-->>API: Top 10 + source timestamps
    API->>Clock: Calculate freshness state
    API->>Cron: Read next refresh time
    Cron-->>API: Next scheduled run
    API-->>UI: Snapshot + age + freshness + next refresh
    UI-->>User: Render top 10 and freshness badge

    alt Snapshot is stale
        UI-->>User: Show stale-data warning and Refresh button
    else Snapshot is fresh
        UI-->>User: Show updated N minutes ago
    end
~~~

The Dashboard load is fast because it reads a completed snapshot; it does not call Alpaca or an LLM on every page load.

## 6. User manually refreshes Dashboard

~~~mermaid
sequenceDiagram
    autonumber
    actor User
    participant UI as Dashboard
    participant API as FastAPI
    participant Limit as Cooldown/Rate Limit
    participant Lock as Run Lock
    participant Graph as Screen Workflow
    participant Cache as Snapshot Cache

    User->>UI: Click Refresh top 10
    UI->>API: POST /dashboard/refresh
    API->>Limit: Check user and global cooldown

    alt Cooldown active
        Limit-->>API: Existing run or retry-after
        API-->>UI: 202 running or 429 retry later
        UI-->>User: Show current run status
    else Allowed
        Limit-->>API: Allowed
        API->>Lock: Acquire refresh lock
        Lock-->>API: Run ID
        API->>Graph: Start asynchronous refresh
        API-->>UI: 202 Accepted + run ID
        loop Until complete or timeout
            UI->>API: GET /runs/run-id
            API-->>UI: queued/running/completed/failed
        end
        UI->>API: GET /dashboard/latest
        API->>Cache: Read published snapshot
        Cache-->>API: New top 10
        API-->>UI: Snapshot
        UI-->>User: Update ranking and timestamp
    end
~~~

## 7. User selects a Dashboard candidate

~~~mermaid
sequenceDiagram
    autonumber
    actor User
    participant UI as Dashboard/Screener
    participant API as FastAPI
    participant Graph as Option Workflow
    participant MCP as Alpaca MCP Gateway
    participant Alpaca as Alpaca MCP Server
    participant Engine as Option Engine
    participant Arize as Arize

    User->>UI: Click candidate
    UI->>UI: Navigate to Screener with ticker
    UI->>API: GET /options?ticker=AAPL
    API->>Graph: Run ticker option workflow
    Graph->>MCP: get_asset
    MCP->>Alpaca: Validate asset
    Alpaca-->>MCP: Active and optionable
    Graph->>MCP: get_stock_snapshot
    MCP->>Alpaca: Request current snapshot
    Alpaca-->>MCP: Spot, quote, timestamps
    Graph->>MCP: get_option_chain(20–35 DTE)
    MCP->>Alpaca: Request bounded chain
    Alpaca-->>MCP: Quotes, IV, Greeks
    MCP-->>Graph: Normalized chain
    Graph->>Engine: Validate and calculate metrics
    Engine-->>Graph: 5 CSP puts + 5 covered calls
    Graph->>Arize: Trace tool timing and result counts
    Graph-->>API: Typed option response
    API-->>UI: Contracts + feed + timestamps
    UI-->>User: Render strategy table
~~~

## 8. User enters any ticker in Screener

~~~mermaid
sequenceDiagram
    autonumber
    actor User
    participant UI as Screener
    participant API as FastAPI
    participant Graph as Option Workflow

    User->>UI: Enter MU and click Screen ticker
    UI->>UI: Validate ticker format
    UI->>API: GET /options?ticker=MU
    API->>Graph: Execute typed workflow

    alt Invalid or inactive asset
        Graph-->>API: Validation error
        API-->>UI: Safe error response
        UI-->>User: Ticker unavailable
    else No eligible 20–35 DTE chain
        Graph-->>API: Empty result + reason
        API-->>UI: No eligible contracts
        UI-->>User: Keep DTE rule; show empty state
    else Eligible
        Graph-->>API: 5 puts + 5 calls
        API-->>UI: Typed response
        UI-->>User: Render contracts and freshness
    end
~~~

## 9. User asks Kezzy a question

~~~mermaid
sequenceDiagram
    autonumber
    actor User
    participant UI as Kezzy Panel
    participant API as Chat API
    participant Graph as Kezzy LangGraph
    participant State as Latest Screen State
    participant MCP as Alpaca MCP Gateway
    participant LLM as OpenAI Model
    participant Guard as Response Validator
    participant Arize as Arize

    User->>UI: Why is AAPL ranked first?
    UI->>API: POST /chat
    API->>Graph: Message + session context
    Graph->>LLM: Classify intent with bounded schema
    LLM-->>Graph: ranking_explanation
    Graph->>State: Read latest AAPL score components
    State-->>Graph: Liquidity, momentum, volatility, run ID
    Graph->>LLM: Explain supplied evidence
    LLM-->>Graph: Draft answer
    Graph->>Guard: Validate numerical grounding

    alt Unsupported number or trading action
        Guard-->>Graph: Reject
        Graph-->>API: Safe refusal/correction
    else Valid
        Guard-->>Graph: Pass
        Graph->>Arize: Record route, evidence, tokens, eval
        Graph-->>API: Grounded answer + run timestamp
    end

    API-->>UI: Response
    UI-->>User: Answer with data age
~~~

For ranking explanations, Kezzy reads the stored snapshot and does not call Alpaca again. For a current quote or news question, the router may call the corresponding allowlisted MCP tool.

## 10. Refresh state machine

~~~mermaid
stateDiagram-v2
    [*] --> Idle
    Idle --> Queued: cron or manual request
    Queued --> Running: lock acquired
    Queued --> Skipped: duplicate lock
    Running --> Validating: MCP fetch complete
    Running --> Failed: provider/tool failure
    Validating --> Publishing: quality gates pass
    Validating --> Failed: incomplete/invalid data
    Publishing --> Completed: atomic pointer updated
    Failed --> Idle: retain last successful snapshot
    Skipped --> Idle
    Completed --> Idle
~~~

## 11. Deployment view

~~~mermaid
flowchart TB
    subgraph WebService[Application Service]
        UI[Static frontend]
        API[FastAPI]
        GRAPH[LangGraph/LangChain]
        MCPCLIENT[MCP client]
        ALPACAPROC[Alpaca MCP child process]
    end

    subgraph Worker[Scheduled Worker]
        SCHED[Scheduler]
        JOB[Screen workflow worker]
        MCPCLIENT2[MCP client]
        ALPACAPROC2[Alpaca MCP child process]
    end

    subgraph Shared
        REDIS[(Cache + distributed lock)]
        DB[(Persistent database)]
        SECRETS[Secret store]
    end

    API --> REDIS
    API --> DB
    SCHED --> JOB
    JOB --> REDIS
    JOB --> DB
    MCPCLIENT --> ALPACAPROC
    MCPCLIENT2 --> ALPACAPROC2
    SECRETS --> ALPACAPROC
    SECRETS --> ALPACAPROC2
~~~

For a classroom demo, API and scheduler may run in one process with an in-process lock. For shared hosting, separate the scheduled worker and use a distributed lock so multiple application replicas cannot publish competing snapshots.

## 12. Scheduler implementation rules

1. Use a real scheduler or managed cron trigger, not a browser timer.
2. Store all timestamps in UTC and use the Alpaca market clock/calendar for session awareness.
3. Generate a unique run ID and idempotency key.
4. Acquire a lock before starting provider calls.
5. Keep the last successful snapshot available throughout refresh.
6. Publish atomically only after all quality gates pass.
7. Release locks in a finally block and use an expiring lease.
8. Apply rate limits and bounded concurrency.
9. Trace every run, including skipped duplicates and failed runs.
10. Display source-data age and next refresh in the UI.

## 13. Recommended implementation order

1. Define DashboardSnapshot, ScreenRun, Candidate, and Contract models.
2. Introduce AlpacaMCPGateway behind the existing deterministic engines.
3. Add snapshot storage and latest-successful pointer.
4. Add the screen LangGraph workflow.
5. Add scheduled/manual run lock and run-status endpoints.
6. Add market-clock-aware cron policy.
7. Add Dashboard freshness badges and next-refresh time.
8. Add Arize spans and dashboards.
9. Add Kezzy after the non-LLM paths are stable.

## 14. Demo evidence

The capstone demo should show:

- a scheduled run in Arize;
- the Alpaca MCP stock-bars tool span;
- deterministic filter/ranking spans;
- atomic publication of a top-10 snapshot;
- Dashboard age and next refresh;
- candidate-to-option sequence;
- one grounded Kezzy explanation;
- proof that the trading toolset is absent.
