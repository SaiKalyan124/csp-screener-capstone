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

The dashboard refresh now emits these code-based scores in `evaluation_scores`:

- `classification_coverage`: fraction of eligible candidates receiving a valid model label;
- `eligible_symbol_precision`: verifies the model introduced no ticker outside the deterministic shortlist;
- `citation_precision`: fraction of returned citations found in retrieved evidence;
- `score_integrity`: verifies model processing did not change deterministic scores;
- `contract_eligibility_integrity`: verifies every output still has five eligible CSPs and five eligible covered calls.

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
