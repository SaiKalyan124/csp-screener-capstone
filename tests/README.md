# Test suite

The test tree mirrors the application component boundaries.

```text
tests/
├── unit/
│   ├── agents/          # Intent parsing, structured output, safety and eval logic
│   ├── configuration/   # Environment and settings behavior
│   ├── domain/          # Pure screening, eligibility and ranking calculations
│   ├── observability/   # Deterministic latency/evaluation helpers
│   ├── retrieval/       # Evidence normalization and retrieval adapters
│   └── services/        # Application-service helper boundaries
└── integration/
    └── workflows/       # Provider-to-workflow behavior with test doubles
```

Run everything with:

```bash
python -m pytest -q
```

Unit tests must not call Alpaca, Yahoo, OpenAI, or Arize. Integration tests use
local fakes unless they are explicitly marked as external smoke tests in the
future. Keep reusable fixtures close to the narrowest folder that needs them;
promote them to `tests/conftest.py` only when several components share them.
