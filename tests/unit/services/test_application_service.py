from datetime import date

from csp_screener.services.parsing import (
    extract_company_names,
    extract_mentioned_tickers,
    parse_budget,
    parse_expiration_date,
    parse_requested_count,
)


def test_budget_parses_k_shorthand() -> None:
    assert parse_budget("I have capital of 50k") == 50_000


def test_budget_parses_currency_with_commas() -> None:
    assert parse_budget("My budget is $40,000") == 40_000


def test_budget_returns_none_without_explicit_amount() -> None:
    assert parse_budget("Show medium-risk CSP candidates") is None


def test_budget_parses_decimal_thousands() -> None:
    assert parse_budget("capital of 12.5k") == 12_500


def test_requested_count_parses_numeric_stock_request() -> None:
    assert parse_requested_count("What 5 stocks should I buy now") == 5


def test_requested_count_parses_words_and_caps_at_five() -> None:
    assert parse_requested_count("Give me ten stocks") == 5
    assert parse_requested_count("Give me five candidates") == 5


def test_extract_company_names_finds_netflix_not_option_jargon() -> None:
    assert extract_company_names(
        "What's the Netflix secured put stock options premium for 09/04?"
    ) == ["Netflix"]
    assert extract_company_names(
        "what is the netflix secured put premium for 09/04?"
    ) == ["netflix"]
    assert extract_mentioned_tickers(
        "What's the Netflix secured put stock options premium for 09/04?"
    ) == []


def test_parse_expiration_date_reads_us_slash_dates() -> None:
    assert parse_expiration_date(
        "premium for 09/04?", today=date(2026, 9, 3)
    ) == date(2026, 9, 4)
    assert parse_expiration_date(
        "NFLX Sep 4 puts", today=date(2026, 9, 3)
    ) == date(2026, 9, 4)
