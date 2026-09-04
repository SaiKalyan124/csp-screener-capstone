from __future__ import annotations

import re
import json
import sys
from functools import lru_cache
from pathlib import Path
from urllib.request import Request, urlopen

# Vercel installs third-party dependencies from pyproject.toml but executes the
# application without installing this repository's src-layout package.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from csp_screener.config import WEB_ROOT, load_settings
from csp_screener.services import ApplicationService
from csp_screener.profiles import normalize_profile


SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


class ProfileInput(BaseModel):
    mode: str = "guided"
    risk_level: str = "medium"
    available_capital: float = 50_000
    dte_min: int = 20
    dte_max: int = 35
    delta_min: float = 0.20
    delta_max: float = 0.30
    max_allocation_pct: float = 30
    max_spread_pct: float = 20
    avoid_earnings: bool = True

    def as_rules(self) -> dict[str, object]:
        try:
            return normalize_profile(self.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


class ChatRequest(BaseModel):
    symbol: str
    question: str
    profile: ProfileInput | None = None


class ProfileRecommendationRequest(BaseModel):
    description: str
    available_capital: float
    current_profile: ProfileInput | None = None


class AuthenticatedUser(BaseModel):
    user_id: str
    email: str
    access_token: str


def profile_from_query(
    mode: str = Query(default="guided"),
    risk_level: str = Query(default="medium"),
    available_capital: float = Query(default=50_000),
    dte_min: int = Query(default=20),
    dte_max: int = Query(default=35),
    delta_min: float = Query(default=0.20),
    delta_max: float = Query(default=0.30),
    max_allocation_pct: float = Query(default=30),
    max_spread_pct: float = Query(default=20),
    avoid_earnings: bool = Query(default=True),
) -> dict[str, object]:
    return ProfileInput(
        mode=mode,
        risk_level=risk_level,
        available_capital=available_capital,
        dte_min=dte_min,
        dte_max=dte_max,
        delta_min=delta_min,
        delta_max=delta_max,
        max_allocation_pct=max_allocation_pct,
        max_spread_pct=max_spread_pct,
        avoid_earnings=avoid_earnings,
    ).as_rules()


@lru_cache(maxsize=1)
def get_service() -> ApplicationService:
    """Reuse provider clients and warm-instance caches across requests."""
    return ApplicationService(load_settings())


app = FastAPI(title="CSP Screener Capstone", docs_url=None, redoc_url=None)


def require_user(
    authorization: str | None = Header(default=None),
) -> AuthenticatedUser | None:
    settings = load_settings()
    if not settings.auth_required:
        return None
    if not settings.supabase_url or not settings.supabase_anon_key:
        raise HTTPException(status_code=503, detail="Hosted authentication is not configured.")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Sign in is required.")
    request = Request(
        settings.supabase_url.rstrip("/") + "/auth/v1/user",
        headers={"apikey": settings.supabase_anon_key, "authorization": authorization},
    )
    try:
        with urlopen(request, timeout=5) as response:
            if response.status != 200:
                raise HTTPException(status_code=401, detail="Your session is invalid.")
            user = json.loads(response.read() or b"{}")
        email = str(user.get("email") or "").strip().lower()
        user_id = str(user.get("id") or "").strip()
        if not user_id:
            raise HTTPException(status_code=401, detail="Your session is invalid.")
        if settings.allowed_emails and email not in settings.allowed_emails:
            raise HTTPException(status_code=403, detail="This account is not approved for access.")
        return AuthenticatedUser(
            user_id=user_id,
            email=email,
            access_token=authorization.removeprefix("Bearer ").strip(),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Your session expired. Sign in again.") from exc


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


@app.get("/api/runtime-config")
def runtime_config() -> dict[str, object]:
    settings = load_settings()
    enabled = bool(
        settings.auth_required and settings.supabase_url and settings.supabase_anon_key
    )
    return {
        "auth_required": enabled,
        "supabase_url": settings.supabase_url if enabled else None,
        "supabase_anon_key": settings.supabase_anon_key if enabled else None,
    }


@app.get("/api/screen")
def screen(
    refresh: bool = Query(default=False),
    research: bool = Query(default=False),
    profile: dict[str, object] = Depends(profile_from_query),
    user: AuthenticatedUser | None = Depends(require_user),
) -> dict[str, object]:
    try:
        result = get_service().screen(force=refresh, research=research, profile=profile)
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/options")
def options(
    symbol: str = Query(...),
    profile: dict[str, object] = Depends(profile_from_query),
    _: None = Depends(require_user),
) -> dict[str, object]:
    normalized = symbol.strip().upper()
    if not SYMBOL_RE.fullmatch(normalized):
        raise HTTPException(status_code=400, detail="Enter a valid ticker symbol.")
    try:
        return get_service().options(normalized, profile=profile)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/chat")
def chat(
    payload: ChatRequest,
    user: AuthenticatedUser | None = Depends(require_user),
) -> dict[str, object]:
    symbol = payload.symbol.strip().upper()
    question = payload.question.strip()
    if not SYMBOL_RE.fullmatch(symbol):
        raise HTTPException(status_code=400, detail="Enter a valid ticker symbol.")
    if not question:
        raise HTTPException(status_code=400, detail="Question is required.")
    try:
        profile = payload.profile.as_rules() if payload.profile else ProfileInput().as_rules()
        return get_service().research(symbol, question, profile=profile)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/profile/recommend")
def recommend_profile(
    payload: ProfileRecommendationRequest,
    user: AuthenticatedUser | None = Depends(require_user),
) -> dict[str, object]:
    try:
        current = payload.current_profile.as_rules() if payload.current_profile else None
        return get_service().recommend_profile(
            payload.description.strip(), payload.available_capital, current
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
