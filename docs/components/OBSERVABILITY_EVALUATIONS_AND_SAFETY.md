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
| Routing | intent accuracy, correct tool, correct arguments, unnecessary calls |
| Retrieval | recall@k, citation precision, deduplication, freshness |
| Generation | groundedness, numerical consistency, completeness, uncertainty |
| End to end | latency, token usage, estimated cost, task success |

Use code-based checks for objective facts and calculations. Use rubric-based model judges only for subjective qualities such as clarity and helpfulness, with sampled human review.

## Safety and compliance boundaries

- Educational research only; no personalized guarantee of profit or safety.
- No order placement or account-changing tools.
- Validate symbols, budgets, DTE, numeric ranges, and request size.
- Treat retrieved documents and tool output as untrusted external data.
- Defend against prompt injection and require source-backed claims.
- Show stale, missing, conflicting, or entitlement-limited data.
- Redact secrets and sensitive user information from logs and traces.
- Require explicit confirmation before any future consequential action.

## Definition of done

- Arize shows complete traces with node latency, tools, retrieval, tokens, and evaluations.
- Regression datasets cover normal, missing-data, adversarial, and prohibited-action cases.
- Quality gates block numerical fabrication, trading calls, uncited material claims, and secret leakage.
- The application remains available if tracing is unavailable.
