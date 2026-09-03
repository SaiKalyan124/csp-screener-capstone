from __future__ import annotations

import re
import sys
from functools import lru_cache
from pathlib import Path

# Vercel installs third-party dependencies from pyproject.toml but executes the
# function from the repository root without installing this src-layout package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from csp_screener.config import WEB_ROOT, load_settings
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


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(WEB_ROOT / "index.html")


@app.get("/styles.css", include_in_schema=False)
def styles() -> FileResponse:
    return FileResponse(WEB_ROOT / "styles.css", media_type="text/css")


@app.get("/app.js", include_in_schema=False)
def javascript() -> FileResponse:
    return FileResponse(WEB_ROOT / "app.js", media_type="application/javascript")


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
