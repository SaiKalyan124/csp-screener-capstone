from __future__ import annotations

from typing import Any, Mapping


DEFAULT_PROFILE: dict[str, object] = {
    "mode": "guided",
    "risk_level": "medium",
    "available_capital": 50_000.0,
    "dte_min": 20,
    "dte_max": 35,
    "delta_min": 0.20,
    "delta_max": 0.30,
    "max_allocation_pct": 30.0,
    "max_spread_pct": 20.0,
    "avoid_earnings": True,
}


def normalize_profile(values: Mapping[str, Any] | None = None) -> dict[str, object]:
    """Return validated profile rules shared by local and hosted transports."""
    supplied = dict(values or {})
    profile = {**DEFAULT_PROFILE, **supplied}
    try:
        profile.update({
            "mode": str(profile["mode"]),
            "risk_level": str(profile["risk_level"]),
            "available_capital": float(profile["available_capital"]),
            "dte_min": int(profile["dte_min"]),
            "dte_max": int(profile["dte_max"]),
            "delta_min": float(profile["delta_min"]),
            "delta_max": float(profile["delta_max"]),
            "max_allocation_pct": float(profile["max_allocation_pct"]),
            "max_spread_pct": float(profile["max_spread_pct"]),
        })
        avoid = profile["avoid_earnings"]
        profile["avoid_earnings"] = (
            avoid if isinstance(avoid, bool)
            else str(avoid).strip().lower() in {"1", "true", "yes", "on"}
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("Profile settings must contain valid numbers.") from exc

    if profile["mode"] not in {"guided", "custom"}:
        raise ValueError("Invalid profile mode.")
    if profile["risk_level"] not in {"low", "medium", "high"}:
        raise ValueError("Invalid risk level.")
    if not 1 <= profile["dte_min"] <= profile["dte_max"] <= 365:
        raise ValueError("Invalid DTE range.")
    if not 0 < profile["delta_min"] <= profile["delta_max"] < 1:
        raise ValueError("Invalid delta range.")
    if profile["available_capital"] < 1_000 or not 5 <= profile["max_allocation_pct"] <= 100:
        raise ValueError("Invalid capital limits.")
    if not 1 <= profile["max_spread_pct"] <= 100:
        raise ValueError("Invalid spread limit.")
    return profile
