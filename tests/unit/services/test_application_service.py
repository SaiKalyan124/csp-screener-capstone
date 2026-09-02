from csp_screener.services.parsing import parse_budget


def test_budget_parses_k_shorthand() -> None:
    assert parse_budget("I have capital of 50k") == 50_000


def test_budget_parses_currency_with_commas() -> None:
    assert parse_budget("My budget is $40,000") == 40_000


def test_budget_returns_none_without_explicit_amount() -> None:
    assert parse_budget("Show medium-risk CSP candidates") is None


def test_budget_parses_decimal_thousands() -> None:
    assert parse_budget("capital of 12.5k") == 12_500
