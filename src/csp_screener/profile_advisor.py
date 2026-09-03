from __future__ import annotations

import os
import time
from typing import Any, TypedDict

from pydantic import BaseModel, Field

from .profiles import normalize_profile


class ProfileProposal(BaseModel):
    risk_level: str = Field(description="low, medium, or high")
    dte_min: int
    dte_max: int
    delta_min: float
    delta_max: float
    max_allocation_pct: float
    max_spread_pct: float
    avoid_earnings: bool
    rationale: list[str] = Field(min_length=2, max_length=3)


class AdvisorState(TypedDict, total=False):
    description: str
    available_capital: float
    current_profile: dict[str, Any]
    raw_proposal: dict[str, Any]
    recommendation: dict[str, Any]
    guardrails: dict[str, Any]


BOUNDS = {
    "low": {
        "dte_min": (21, 45), "dte_max": (30, 75),
        "delta_min": (0.05, 0.18), "delta_max": (0.12, 0.25),
        "max_allocation_pct": (10, 25), "max_spread_pct": (8, 20),
    },
    "medium": {
        "dte_min": (14, 35), "dte_max": (25, 60),
        "delta_min": (0.10, 0.25), "delta_max": (0.20, 0.35),
        "max_allocation_pct": (15, 40), "max_spread_pct": (10, 25),
    },
    "high": {
        "dte_min": (7, 30), "dte_max": (21, 75),
        "delta_min": (0.15, 0.35), "delta_max": (0.25, 0.45),
        "max_allocation_pct": (20, 50), "max_spread_pct": (10, 30),
    },
}


def _validate_request(state: AdvisorState) -> dict[str, Any]:
    description = state.get("description", "").strip()
    capital = float(state.get("available_capital", 0) or 0)
    if not 20 <= len(description) <= 800:
        raise ValueError("Describe your goals and risk preferences in 20–800 characters.")
    if not 1_000 <= capital <= 100_000_000:
        raise ValueError("Available capital must be between $1,000 and $100,000,000.")
    return {"description": description, "available_capital": capital}


def _recommend_with_llm(state: AdvisorState) -> dict[str, Any]:
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_openai import ChatOpenAI

    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            "You configure research filters for a cash-secured-put screener. Interpret "
            "the user's stated assignment tolerance, time horizon, income preference, "
            "capital concentration tolerance, and earnings-event preference. Recommend "
            "low, medium, or high plus numeric screening parameters. This is configuration "
            "guidance, not investment advice. Do not select securities, predict returns, "
            "or change the supplied capital. Give two or three short rationale statements.",
        ),
        (
            "human",
            "User description: {description}\nAvailable capital: ${capital}\n"
            "Current profile: {current_profile}\nAllowed parameter envelopes: {bounds}",
        ),
    ])
    model = ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", "gpt-5-mini"), temperature=0
    ).with_structured_output(ProfileProposal)
    proposal = (prompt | model).invoke({
        "description": state["description"],
        "capital": state["available_capital"],
        "current_profile": state.get("current_profile", {}),
        "bounds": BOUNDS,
    })
    return {"raw_proposal": proposal.model_dump()}


def _validate_proposal(state: AdvisorState) -> dict[str, Any]:
    raw = dict(state["raw_proposal"])
    risk = str(raw.get("risk_level", "medium")).lower()
    if risk not in BOUNDS:
        risk = "medium"
    changes: list[str] = []
    bounded: dict[str, Any] = {}
    for field, (minimum, maximum) in BOUNDS[risk].items():
        value = float(raw[field])
        clamped = min(max(value, minimum), maximum)
        if clamped != value:
            changes.append(f"{field} constrained to the approved {risk}-risk range")
        bounded[field] = int(clamped) if field.startswith("dte_") else round(clamped, 2)

    if bounded["dte_min"] > bounded["dte_max"]:
        bounded["dte_min"], bounded["dte_max"] = bounded["dte_max"], bounded["dte_min"]
        changes.append("DTE limits reordered")
    if bounded["delta_min"] > bounded["delta_max"]:
        bounded["delta_min"], bounded["delta_max"] = bounded["delta_max"], bounded["delta_min"]
        changes.append("delta limits reordered")

    recommendation = normalize_profile({
        "mode": "custom",
        "risk_level": risk,
        "available_capital": state["available_capital"],
        **bounded,
        "avoid_earnings": bool(raw.get("avoid_earnings", True)),
    })
    rationale = [str(item).strip()[:180] for item in raw.get("rationale", []) if str(item).strip()][:3]
    return {
        "recommendation": {**recommendation, "rationale": rationale},
        "guardrails": {
            "status": "adjusted" if changes else "passed",
            "adjustments": changes,
            "capital_preserved": recommendation["available_capital"] == state["available_capital"],
            "requires_user_approval": True,
            "saved_automatically": False,
        },
    }


def build_profile_advisor_graph():
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(AdvisorState)
    graph.add_node("validate_profile_request", _validate_request)
    graph.add_node("interpret_preferences_with_llm", _recommend_with_llm)
    graph.add_node("enforce_deterministic_parameter_bounds", _validate_proposal)
    graph.add_edge(START, "validate_profile_request")
    graph.add_edge("validate_profile_request", "interpret_preferences_with_llm")
    graph.add_edge("interpret_preferences_with_llm", "enforce_deterministic_parameter_bounds")
    graph.add_edge("enforce_deterministic_parameter_bounds", END)
    return graph.compile()


class ProfileAdvisor:
    def __init__(self) -> None:
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is required for Profile Advisor")
        self.graph = build_profile_advisor_graph()

    def recommend(
        self, description: str, available_capital: float,
        current_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        result = self.graph.invoke({
            "description": description,
            "available_capital": available_capital,
            "current_profile": current_profile or {},
        })
        return {
            "workflow": "langgraph-profile-advisor",
            "recommendation": result["recommendation"],
            "guardrails": result["guardrails"],
            "latency_ms": round((time.perf_counter() - started) * 1000),
        }
