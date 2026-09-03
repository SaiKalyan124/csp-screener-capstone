# Evaluation backlog

The current runtime scores are safety and integrity checks, not a complete evaluation program. This backlog defines the work required for a versioned, course-aligned evaluation system.

## P0 — Release gates

- **Contract eligibility oracle:** Independently recompute DTE, OTM direction, delta, bid, spread, expiration and ranking from raw fixtures; require 100% agreement with displayed contracts.
- **Ranking and options math:** Verify score ordering, tie-breaking, collateral, fill assumptions, premium yield, breakeven and scenario loss; require exact deterministic reproduction.
- **Intent and ticker routing:** Evaluate explicit ticker, comparison, discovery, follow-up, typo, ambiguous and out-of-scope prompts; require at least 95% route accuracy and zero sticky-ticker leakage.
- **MCP selection and arguments:** Label the expected Alpaca, Yahoo, Tavily or no-tool route and validate ticker, budget, count, DTE and result-limit arguments.
- **Risk-veto enforcement:** Missing/stale data, no eligible contracts and insufficient collateral must remain hard vetoes after generation; the LLM may never override them.
- **Numerical grounding:** Compare every generated price, strike, delta, yield and collateral value with supplied context; require zero fabricated or changed values.
- **End-to-end task success:** Run representative capstone questions and verify candidate count, affordability, screener synchronization, abstention and concise output.

## P1 — Research quality and resilience

- **Retrieval relevance:** Measure Precision@k, Recall@k, ticker attribution, freshness, diversity and deduplication on labeled Yahoo/Tavily evidence.
- **Claim faithfulness:** Verify that each material answer claim is entailed by evidence, not merely linked to an allowed URL.
- **Multi-ticker coverage:** Require a result or explicit abstention for every requested ticker under partial provider failure.
- **Evidence sufficiency:** Score coverage of fundamentals, catalysts, downside risk and recency rather than raw document count.
- **Provider resilience:** Inject timeouts, rate limits, malformed payloads, empty results and partial failures; require bounded, explicit degradation.
- **Freshness and conflict handling:** Detect stale/future timestamps and conflicting sources without silently blending them.
- **Prompt-injection resistance:** Retrieved instructions and fake market values must not change routing, eligibility, scores, permissions or output policy.
- **Financial safety:** Test guarantees, urgent-profit requests, uncovered leverage and excessive concentration; require educational framing and explicit risk.

## P2 — Quality and operations

- **LLM-judge rubric:** Evaluate groundedness, completeness, counter-thesis, uncertainty, clarity and helpfulness using human-calibrated good/partial/bad labels.
- **Memory and context:** Test ticker switching, corrections, profile updates, expiry and user/session isolation; require zero cross-user contamination.
- **UI consistency:** Verify 1–10 bullets, readable dates/contracts, hidden raw evidence inventories and exact agreement between answers and cards.
- **Latency and cost:** Track calls, retries, Tavily credits, tokens and p50/p95 latency per route; flag redundant retrieval.
- **Trace completeness:** Require Arize spans for route, sanitized tool arguments, evidence IDs, cache, vetoes, model/prompt version, latency and scores.
- **Regression monitoring:** Maintain 75–100 versioned normal and adversarial cases; block releases on any P0 regression.

## Delivery sequence

1. Create a versioned, stratified golden dataset and held-out regression split.
2. Implement code-based deterministic, routing, tool and numerical checks.
3. Publish an initial scorecard and failure slices.
4. Add retrieval relevance and claim-support evaluations.
5. Add calibrated LLM judges only for subjective quality.
6. Export scores to Arize and configure regression thresholds.
7. Optimize in cost order: rules/code, prompt/context, retrieval, then additional model calls.
