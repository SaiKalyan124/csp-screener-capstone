import json
from pathlib import Path

from csp_screener.tool_routing import evaluate_tool_routes


def test_tool_routing_dataset() -> None:
    cases = json.loads(
        (Path(__file__).parent / "datasets" / "routing_cases.json").read_text(encoding="utf-8")
    )
    assert evaluate_tool_routes(cases) == {
        "intent_accuracy": 1.0,
        "primary_tool_exact_match": 1.0,
        "profile_unnecessary_tool_rate": 0.0,
    }
