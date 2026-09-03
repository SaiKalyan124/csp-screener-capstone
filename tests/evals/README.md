# Evaluation harness

This folder contains versioned, repeatable cases for behavior that unit tests
alone cannot describe clearly. The first dataset evaluates deterministic MCP
routing before an LLM or external tool is called.

Routing scores:

- `intent_accuracy`: the selected research intent matches the labeled case.
- `primary_tool_exact_match`: the ordered primary tool plan matches exactly.
- `unnecessary_tool_rate`: profile-only questions do not call market tools.

The router makes the production decision. These evals measure it and block a
regression when a prompt or routing rule changes. Future datasets will cover
retrieval relevance, grounding, safety, and response quality.
