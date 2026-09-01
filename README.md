# CSP Screener Capstone

A capstone application for screening stocks and options for cash-secured-put (CSP) research. It combines deterministic eligibility and ranking calculations with Alpaca market data, an optional LangChain/LangGraph research agent, and Arize tracing.

The application is research-only: it does not place trades or provide personalized financial advice.

## What the demo does

- Maintains a dashboard of ten CSP-eligible candidates from a configured universe.
- Screens any ticker and displays five cash-secured puts and five covered calls near the current stock price.
- Calculates affordability, strike distance, premium yield, volatility, liquidity, and other ranking inputs deterministically.
- Lets the research agent answer ticker, comparison, budget, risk, and follow-up questions using current screen results as grounded context.
- Refreshes dashboard data in the background and caches the latest result.
- Exports LangChain/LangGraph traces to Arize when Arize credentials are configured.
- Includes a CLI for measuring Alpaca stock and option-data latency.

## Current iterations

| Iteration | Status | Scope |
|---|---|---|
| 1 | Implemented | Alpaca data, deterministic CSP eligibility/ranking, dashboard, ticker screener, caching, scheduled refresh |
| 2 | In progress | LangChain components inside a LangGraph research workflow, grounded answers, follow-ups, Arize tracing |
| 3 | Planned | Profile and durable memory, position-aware routing, stronger RAG, evaluations and guardrails |

## Architecture

Review the approved end-state design in either format:

- [GitHub-rendered architecture and Mermaid diagrams](docs/ARCHITECTURE.md)
- [Single-page HTML architecture review](docs/architecture-review.html)

```text
Iteration 1 — Deterministic CSP Screener
Alpaca market data
   -> eligibility filters and CSP calculations
   -> ranked dashboard and ticker option screen
   -> cache and scheduled refresh

Iteration 2 — Grounded Research Agent
Iteration 1 screen results
   + company evidence and news retrieval
   -> LangChain tools inside a LangGraph workflow
   -> comparisons, budget/risk questions and follow-ups
   -> Arize traces and evaluations

Iteration 3 — Personalized, Position-Aware Assistant
Iteration 2 research workflow
   + user profile and durable memory
   + portfolio and current-position context
   -> CSP versus covered-call routing
   -> alerts, guardrails and monitored recommendations
```

Each iteration remains independently testable. Iteration 1 owns deterministic financial calculations; Iteration 2 adds evidence-grounded AI research without replacing those calculations; Iteration 3 adds personalization, memory, and position-aware routing.

### Iteration 1: deterministic screening

- Pull stock and option-chain data from Alpaca.
- Apply explicit eligibility, affordability, liquidity, volatility, and risk rules.
- Rank the top CSP candidates without an LLM.
- Display the dashboard and ticker-specific option screen.
- Cache results and refresh dashboard data on a schedule.

### Iteration 2: research and reasoning

- Use LangGraph to route research and follow-up requests.
- Use LangChain for model, tool, retrieval, and structured-output integrations.
- Ground responses in deterministic screen results and retrieved company evidence.
- Support ticker discovery, comparisons, budget constraints, risk questions, and conversational follow-ups.
- Trace workflow steps, latency, inputs, and outputs with Arize.

### Iteration 3: profile, memory, and portfolio context

- Store a small user profile: budget, risk preference, timeline, sectors, and strategy constraints.
- Add durable conversation and research memory with clear retention boundaries.
- Incorporate owned shares, open positions, watchlists, and buying power.
- Route between CSP research, covered-call research, general investing questions, and alerts.
- Add stronger evaluations, safety guardrails, freshness checks, and human confirmation before consequential actions.

## Development workstreams

The project is organized into independent workstreams with clear component boundaries:

| Workstream | Responsibility | Primary paths | Stable interface |
|---|---|---|---|
| Market data | Alpaca API/MCP adapters, normalization, latency | `src/csp_screener/providers/` | `latest_trade`, `option_chain`, `daily_bars` |
| CSP ranking | Eligibility rules, scoring, contract selection | `src/csp_screener/iteration1.py`, `src/csp_screener/workflows/` | `IterationOneWorkflow.screen/options` |
| Research agent | Intent routing, RAG, follow-ups, memory | `src/csp_screener/iteration2.py`, `src/csp_screener/agents/` | `ResearchAgent.ask` |
| Observability/evals | Arize spans, datasets, regression metrics | `src/csp_screener/observability.py`, `tests/` | Trace names and evaluation fixtures |
| Application/API | Cache, scheduler, validation, API contracts | `src/csp_screener/services/`, `src/csp_screener/server.py` | `/api/screen`, `/api/options`, `/api/chat` |
| Frontend | Dashboard, screener, profile and chat UX | `web/` | API response contracts |
| QA/deployment | Integration tests, fixtures, hosting and runbooks | `tests/`, `docs/`, deployment configuration | Release checks |

Detailed flows and component boundaries are documented in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Repository layout

```text
capstone/
├── src/csp_screener/
│   ├── agents/             # Public research-agent interface
│   ├── providers/          # External market-data adapters
│   ├── services/           # Application orchestration and caching
│   ├── workflows/          # Public workflow interfaces
│   ├── config.py           # Centralized runtime configuration
│   ├── iteration1.py       # Deterministic CSP workflow
│   ├── iteration2.py       # LangGraph research workflow
│   ├── observability.py    # Arize/OpenTelemetry setup
│   ├── server.py           # Thin HTTP transport
│   └── cli.py              # Alpaca latency benchmark CLI
├── web/                    # Vanilla HTML, CSS and JavaScript UI
├── tests/                  # Unit and workflow tests
├── docs/                   # Architecture and component specifications
├── .env.example            # Safe configuration template
└── pyproject.toml          # Python package and dependencies
```

## Prerequisites

- Python 3.11 or newer
- Git
- An Alpaca Market Data API key and secret
- Optional: an OpenAI API key for live agent responses
- Optional: Arize space/API credentials for hosted tracing

## Quick setup

### 1. Clone the repository

```bash
git clone <repository-url>
cd capstone
```

### 2. Create a virtual environment

Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
```

macOS or Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install the project

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

### 4. Configure credentials

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

macOS or Linux:

```bash
cp .env.example .env
```

Edit `.env`:

```dotenv
ALPACA_API_KEY=your_market_data_key
ALPACA_SECRET_KEY=your_market_data_secret

# Optional agent and tracing configuration
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5.6-luna
ARIZE_SPACE_ID=
ARIZE_API_KEY=
ARIZE_PROJECT_NAME=csp-screener-capstone
```

Never commit `.env`. It is already excluded by `.gitignore`.

If credentials must be shared from another local file, set `CSP_SHARED_ENV_FILE` to that file's path before starting the application. A repository-local `.env` remains the recommended setup.

### 5. Run the tests

```bash
python -m pytest -q
```

### 6. Start the web application

```bash
python -m csp_screener.server
```

Alternatively, after installation:

```bash
csp-demo
```

Open [http://127.0.0.1:8080](http://127.0.0.1:8080).

## API endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/screen` | Return cached dashboard candidates |
| `GET` | `/api/screen?refresh=1` | Force a fresh dashboard screen |
| `GET` | `/api/options?symbol=MU` | Return the selected ticker's option candidates |
| `POST` | `/api/chat` | Ask the research agent a ticker-specific question |

Example chat request:

```json
{
  "symbol": "MU",
  "question": "Give me three CSP candidates that fit a $50,000 budget."
}
```

## Alpaca latency benchmark

Run the default benchmark:

```bash
csp-benchmark --runs 5 --warmups 1
```

Limit the option request to a strike and expiration window:

```bash
csp-benchmark --underlying SPY --strike-low 550 --strike-high 750 --dte-min 7 --dte-max 30 --runs 10
```

Reports are appended to `results/benchmarks.jsonl`. Compare minimum, median, and p95 latency; the first call may include connection setup.

## Course workflow smoke test

```bash
python -m csp_screener.course_e2e
```

This exercises LangGraph routing, Yahoo SEC-filing metadata retrieval, LangChain invocation, and OpenTelemetry tracing. With Arize credentials, traces are exported to Arize. Without an OpenAI key, the smoke test uses a deterministic fake chat model.

## Development workflow

1. Choose one workstream and avoid mixing unrelated component changes.
2. Create a feature branch: `git switch -c feature/<short-description>`.
3. Preserve the stable interface listed in the workstream table, or coordinate the contract change first.
4. Add focused tests for the component being changed.
5. Run `python -m pytest -q` before opening a pull request.
6. In the pull request, describe changed contracts, test evidence, UI screenshots when relevant, and any new environment variables.

## Troubleshooting

### Alpaca credentials are missing

Confirm `.env` exists in the repository root and contains `ALPACA_API_KEY` and `ALPACA_SECRET_KEY`. Alpaca-compatible names `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` are also accepted.

### PowerShell blocks environment activation

Activation is optional. Run commands through the environment directly:

```powershell
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m csp_screener.server
```

### Port 8080 is already in use

Stop the existing local process using that port, then start the application again.

### The agent has no live model response

Add `OPENAI_API_KEY` to `.env`. Deterministic screening and Alpaca option data do not require OpenAI.

### No Arize traces appear

Verify `ARIZE_SPACE_ID`, `ARIZE_API_KEY`, and `ARIZE_PROJECT_NAME`, then run the course smoke test or make a chat request. Check the selected project and time range in Arize.

## Security and data notes

- Credentials stay on the Python server and are never sent to the browser.
- Do not commit `.env`, trace exports containing sensitive prompts, or private portfolio data.
- Market-data availability depends on Alpaca account entitlements.
- Scores and eligibility rules are capstone examples and must be evaluated before real-world use.

## Documentation

- [Architecture and iteration flows](docs/ARCHITECTURE.md)
- [Market data and screening](docs/components/MARKET_DATA_AND_SCREENING.md)
- [Research agent and RAG](docs/components/RESEARCH_AGENT_AND_RAG.md)
- [Application API and UI](docs/components/APPLICATION_API_AND_UI.md)
- [Observability, evaluations, and safety](docs/components/OBSERVABILITY_EVALUATIONS_AND_SAFETY.md)
