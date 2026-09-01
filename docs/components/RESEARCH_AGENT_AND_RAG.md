# Research agent and RAG

## Responsibility

This component interprets research questions, selects a bounded workflow, retrieves relevant company evidence, and produces structured answers grounded in deterministic market context and citations.

## Usage paradigm

Iteration 2 is a bounded workflow agent, not an unrestricted autonomous agent. LangGraph controls routing and state; LangChain supplies model, tool, retrieval, and structured-output integrations.

Supported routes include:

- explain a ticker or ranked candidate;
- compare supplied tickers;
- discover affordable CSP candidates;
- answer budget, risk, DTE, and delta questions;
- retrieve company fundamentals, catalysts, and risks;
- handle follow-up requests such as selecting a safer strike.

## Dashboard shortlist classification

The dashboard uses a bounded research workflow after the deterministic screen:

1. Code applies hard eligibility rules and produces the Top 10.
2. Filing metadata and recent company news are retrieved for those symbols in parallel.
3. One structured LLM call assigns `favorable`, `watch`, `avoid`, or `insufficient_evidence` with a concise reason and allowed citations.
4. The UI may group or reorder the eligible shortlist by classification, while preserving every deterministic score.
5. If retrieval or the model fails, the deterministic Top 10 remains available and the response is marked `fallback`.

The LLM cannot introduce a new ticker, change market values, override hard eligibility, or promise performance.

## Evidence sources

- SEC filings and material filing sections;
- earnings releases and investor-relations documents;
- available earnings-call transcripts;
- regulatory and legal updates;
- reputable company and industry news.

Structured prices, Greeks, ratios, dates, and technical indicators remain tool data rather than vector-store documents.

## Retrieval design

```mermaid
flowchart LR
    Sources --> Parse[Parse and section-aware chunk]
    Parse --> Metadata[Attach ticker, type, section, date, URL, hash]
    Metadata --> Keyword[(Keyword index)]
    Metadata --> Vector[(Vector index)]
    Question --> Hybrid[Hybrid retrieval]
    Keyword --> Hybrid
    Vector --> Hybrid
    Hybrid --> Rerank[Rerank and deduplicate]
    Rerank --> Answer[Grounded structured answer]
```

Every retrieved chunk carries ticker, document type, publication/filed date, section, source URL, retrieval time, and content hash. Claims must cite returned evidence or be labeled as inference.

## Memory evolution

- Working memory: current question, screen results, and recent turns.
- Episodic memory: previous research sessions and outcomes.
- Semantic memory: budget, risk preference, timeline, and sectors.
- Procedural memory: preferred CSP constraints and response style.

Only working memory is needed initially. Durable memory belongs to Iteration 3 and requires retention, update, and deletion controls.
