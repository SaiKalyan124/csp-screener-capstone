import pytest

from csp_screener.profiles import normalize_profile
from csp_screener.server import _profile_from_query


def test_profile_query_is_normalized_for_local_server() -> None:
    profile = _profile_from_query({
        "mode": ["custom"],
        "risk_level": ["low"],
        "available_capital": ["80000"],
        "dte_min": ["30"],
        "dte_max": ["45"],
        "delta_min": ["0.10"],
        "delta_max": ["0.20"],
        "max_allocation_pct": ["25"],
        "max_spread_pct": ["15"],
        "avoid_earnings": ["false"],
    })

    assert profile["available_capital"] == 80_000
    assert profile["max_allocation_pct"] == 25
    assert profile["avoid_earnings"] is False


def test_profile_rejects_invalid_ranges() -> None:
    with pytest.raises(ValueError, match="Invalid DTE range"):
        normalize_profile({"dte_min": 50, "dte_max": 20})
