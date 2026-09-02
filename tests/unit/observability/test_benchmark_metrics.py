from csp_screener.benchmark import Timing, percentile, summarize


def test_percentile_is_deterministic_for_unsorted_values() -> None:
    assert percentile([30.0, 10.0, 20.0], 0.5) == 20.0
    assert percentile([], 0.95) == 0.0


def test_summarize_reports_latency_distribution_and_latest_count() -> None:
    result = summarize([
        Timing(elapsed_ms=10.0, item_count=2),
        Timing(elapsed_ms=30.0, item_count=5),
        Timing(elapsed_ms=20.0, item_count=3),
    ])

    assert result == {
        "runs": 3,
        "min_ms": 10.0,
        "median_ms": 20.0,
        "p95_ms": 30.0,
        "max_ms": 30.0,
        "last_item_count": 3,
    }
