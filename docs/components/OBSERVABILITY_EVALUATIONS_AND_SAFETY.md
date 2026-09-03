# Observability, evaluations, and safety

## Responsibility

This component makes every workflow measurable and enforces research-only boundaries. Arize receives OpenTelemetry/OpenInference traces without credentials or private portfolio information.

## Trace hierarchy

```text
request
├── route
├── market_data
├── deterministic_calculation
├── retrieval
├── model
└── response_validation
```

Record iteration, workflow, ticker count, provider/tool name, success, retry count, cache status, node latency, model, prompt version, input/output tokens, evidence IDs, and evaluation scores.

## Evaluations

| Component | Primary metrics |
|---|---|
| Ranking | eligibility accuracy, score reproducibility, rejection reasons |
| Provider | contract conformance, freshness, timeout and retry behavior |
| Routing | intent accuracy, primary-tool exact match, fallback correctness, argument validity, unnecessary-call rate |
| Retrieval | recall@k, citation precision, deduplication, freshness |
| Generation | groundedness, numerical consistency, completeness, uncertainty |
| End to end | latency, token usage, estimated cost, task success |

Use code-based checks for objective facts and calculations. Use rubric-based model judges only for subjective qualities such as clarity and helpfulness, with sampled human review.

The dashboard refresh now emits these code-based scores in `evaluation_scores`:

- `classification_coverage`: fraction of eligible candidates receiving a valid model label;
- `eligible_symbol_precision`: verifies the model introduced no ticker outside the deterministic shortlist;
- `citation_precision`: fraction of returned citations found in retrieved evidence;
- `score_integrity`: verifies model processing did not change deterministic scores;
- `contract_eligibility_integrity`: verifies every dashboard output still has five eligible CSPs; covered calls remain optional context.

## Tool routing and its evaluation

The production router chooses a bounded evidence plan before generation. Evals do not choose tools; they replay labeled questions and score whether the router selected the expected provider and avoided unnecessary calls.

| Need | Preferred source | Fallback | Current runtime status |
|---|---|---|---|
| Stock and option prices, quotes, chains, Greeks | Alpaca market data | Yahoo price context | Live through `alpaca-py`; migration to Alpaca MCP remains open |
| Filings and earnings metadata | Yahoo Finance | Tavily public-web search | Live through the local Yahoo Finance MCP |
| Recent company, sector, regulatory, and macro research | Alpaca news plus Tavily search | Yahoo news | Tavily MCP is designed but not yet connected to the Python runtime |
| Profile-only configuration help | Saved profile and deterministic bounds | None | Live; no market tool should be called |

The versioned routing dataset is in `tests/evals/datasets/routing_cases.json`. Its first release measures `intent_accuracy` and `primary_tool_exact_match`; retrieval relevance, fallback behavior, argument correctness, grounding, and safety need separate datasets rather than being inferred from unit-test pass rates.

LangChain/OpenInference automatically traces the LangGraph nodes and model call. When `ARIZE_SPACE_ID` and `ARIZE_API_KEY` are configured, those spans export to the `csp-screener-capstone` Arize project. Without them, the same spans use the local console exporter. Arize-hosted evaluators and monitoring thresholds remain a separate deployment step.

## Safety and compliance boundaries

- Educational research only; no personalized guarantee of profit or safety.
- No order placement or account-changing tools.
- Validate symbols, budgets, DTE, numeric ranges, and request size.
- Treat retrieved documents and tool output as untrusted external data.
- Defend against prompt injection and require source-backed claims.
- Show stale, missing, conflicting, or entitlement-limited data.
- Redact secrets and sensitive user information from logs and traces.
- Require explicit confirmation before any future consequential action.
