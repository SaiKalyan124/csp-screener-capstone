# CSP Screener architecture

For a navigable single-page visual review, see [architecture-review.html](architecture-review.html). This HTML artifact presents the same target architecture with current and planned components distinguished explicitly.

## Iteration model

```mermaid
flowchart TD
    I1[Iteration 1: deterministic screening] --> I2[Iteration 2: CSP Research Intelligence]
    I2 --> I3[Iteration 3: profile, memory, and position-aware assistance]

    I1 --- A[Alpaca market data]
    I1 --- B[Eligibility, ranking, option calculations]
    I1 --- C[Dashboard, screener, cache, refresh]

    I2 --- D[LangChain and LangGraph]
    I2 --- E[Company-evidence retrieval]
    I2 --- F[Arize traces and evaluations]

    I3 --- G[User profile and durable memory]
    I3 --- H[Portfolio and position context]
    I3 --- J[Guardrails, alerts, and confirmations]
```

Iteration 1 owns all numerical calculations. Iteration 2 classifies the deterministically eligible Top 10 as favorable, watch, avoid, or insufficient evidence using bounded retrieved research. It may change display order within that shortlist but cannot make an ineligible candidate eligible or rewrite a numerical score. Iteration 3 adds personalization without changing those trust boundaries.

## High-level component flow

```mermaid
flowchart LR
    UI[Browser UI] --> API[HTTP API]
    API --> APP[Application service]
    APP --> SCREEN[Deterministic screen workflow]
    APP --> AGENT[Research workflow]
    SCREEN --> PROVIDER[Market-data provider]
    AGENT --> PROVIDER
    AGENT --> RAG[Evidence retrieval]
    PROVIDER --> ALPACA[Alpaca API or MCP]
    SCREEN --> CACHE[(Latest snapshot)]
    AGENT --> LLM[Language model]
    APP -. traces .-> ARIZE[Arize]
    SCREEN -. traces .-> ARIZE
    AGENT -. traces .-> ARIZE
```

## Dashboard sequence

```mermaid
sequenceDiagram
    participant User
    participant UI
    participant API
    participant Cache
    participant Screen
    participant Alpaca

    User->>UI: Open dashboard
    UI->>API: GET /api/screen
    API->>Cache: Read latest snapshot
    alt fresh snapshot exists
        Cache-->>API: Ranked and researched candidates
    else refresh required
        API->>Screen: Run deterministic screen
        Screen->>Alpaca: Batched daily bars request
        Alpaca-->>Screen: Bars for configured universe
        Screen->>Screen: Validate, calculate, rank
        Screen->>Screen: Hard-filter and rank the stock pool
        Screen->>Alpaca: Validate bounded option chains for ranked pool
        Screen->>Screen: Require five eligible CSPs and five eligible calls
        Screen->>API: Fully eligible Top 10 with cached chains
    end
    API->>Workflow: Invoke dashboard LangGraph
    Workflow->>Workflow: Retrieve evidence in parallel
    Workflow->>Workflow: One LangChain structured LLM classification call
    Workflow->>Workflow: Validate symbols, citations, scores, and eligibility
    Workflow-->>API: Labels, citations, and evaluation scores
    API->>Cache: Publish combined snapshot
    API-->>UI: Deterministic scores, research labels, citations, freshness
```

## Ticker and research sequence

```mermaid
sequenceDiagram
    participant User
    participant UI
    participant API
    participant Workflow
    participant Alpaca
    participant Retrieval
    participant Model

    User->>UI: Enter ticker or research question
    UI->>API: Options or chat request
    API->>Workflow: Validated request
    Workflow->>Alpaca: Latest trade and bounded option chain
    Alpaca-->>Workflow: Timestamped market data
    Workflow->>Workflow: Apply DTE, OTM, bid, spread, and delta eligibility
    Workflow->>Workflow: Rank by delta fit, spread quality, and bid liquidity
    opt evidence is required
        Workflow->>Retrieval: Retrieve company evidence
        Retrieval-->>Workflow: Reranked cited passages
        Workflow->>Model: Structured market context and evidence
        Model-->>Workflow: Grounded structured response
    end
    Workflow-->>UI: Contracts, explanation, risk, and citations
```

## Cross-cutting rules

- External data must retain source and freshness timestamps.
- Failed refreshes never replace the last successful snapshot.
- Trading and account-modification tools are outside the allowed capability set.
- Secrets stay in server-side environment variables and are excluded from traces.
- Every numerical claim must trace to deterministic state or provider output.
- Dashboard research is a bounded classification layer after eligibility; failure preserves the deterministic Top 10 and is shown as a fallback.
- Each component exposes a stable interface and remains independently testable.

## Component documents

- [Market data and screening](components/MARKET_DATA_AND_SCREENING.md)
- [Research agent and RAG](components/RESEARCH_AGENT_AND_RAG.md)
- [Application API and UI](components/APPLICATION_API_AND_UI.md)
- [Observability, evaluations, and safety](components/OBSERVABILITY_EVALUATIONS_AND_SAFETY.md)
