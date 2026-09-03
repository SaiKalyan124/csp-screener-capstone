from __future__ import annotations

import re
from functools import lru_cache

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from csp_screener.config import load_settings
from csp_screener.services import ApplicationService


SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


class ChatRequest(BaseModel):
    symbol: str
    question: str


@lru_cache(maxsize=1)
def get_service() -> ApplicationService:
    """Reuse provider clients and warm-instance caches across requests."""
    return ApplicationService(load_settings())


app = FastAPI(title="CSP Screener Capstone", docs_url=None, redoc_url=None)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/screen")
def screen(
    refresh: bool = Query(default=False),
    research: bool = Query(default=False),
) -> dict[str, object]:
    try:
        return get_service().screen(force=refresh, research=research)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/options")
def options(symbol: str = Query(...)) -> dict[str, object]:
    normalized = symbol.strip().upper()
    if not SYMBOL_RE.fullmatch(normalized):
        raise HTTPException(status_code=400, detail="Enter a valid ticker symbol.")
    try:
        return get_service().options(normalized)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/chat")
def chat(payload: ChatRequest) -> dict[str, object]:
    symbol = payload.symbol.strip().upper()
    question = payload.question.strip()
    if not SYMBOL_RE.fullmatch(symbol):
        raise HTTPException(status_code=400, detail="Enter a valid ticker symbol.")
    if not question:
        raise HTTPException(status_code=400, detail="Question is required.")
    try:
        return get_service().research(symbol, question)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
