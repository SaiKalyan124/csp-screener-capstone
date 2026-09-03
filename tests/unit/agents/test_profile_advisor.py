import pytest

from csp_screener.profile_advisor import _validate_proposal, _validate_request


def test_profile_advisor_validates_request_without_llm() -> None:
    result = _validate_request({
        "description": "I prefer a low chance of assignment and want to avoid earnings.",
        "available_capital": 50_000,
    })
    assert result["available_capital"] == 50_000


def test_profile_advisor_rejects_vague_request() -> None:
    with pytest.raises(ValueError, match="20–800"):
        _validate_request({"description": "low risk", "available_capital": 50_000})


def test_deterministic_guardrail_clamps_llm_proposal_and_preserves_capital() -> None:
    result = _validate_proposal({
        "available_capital": 50_000,
        "raw_proposal": {
            "risk_level": "low",
            "dte_min": 1,
            "dte_max": 200,
            "delta_min": 0.01,
            "delta_max": 0.80,
            "max_allocation_pct": 90,
            "max_spread_pct": 80,
            "avoid_earnings": True,
            "rationale": ["Prefers assignment cushion.", "Avoids concentrated positions."],
        },
    })
    recommendation = result["recommendation"]
    assert recommendation["available_capital"] == 50_000
    assert recommendation["dte_min"] == 21
    assert recommendation["dte_max"] == 75
    assert recommendation["delta_max"] == 0.25
    assert recommendation["max_allocation_pct"] == 25
    assert result["guardrails"]["status"] == "adjusted"
    assert result["guardrails"]["requires_user_approval"] is True
    assert result["guardrails"]["saved_automatically"] is False
