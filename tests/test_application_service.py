from csp_screener.services import ApplicationService


def test_budget_parses_k_shorthand() -> None:
    assert ApplicationService._budget("I have capital of 50k") == 50_000


def test_budget_parses_currency_with_commas() -> None:
    assert ApplicationService._budget("My budget is $40,000") == 40_000
