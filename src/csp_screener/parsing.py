from __future__ import annotations

import re
from datetime import date


_IGNORED_TICKERS = frozenset({
    "I", "A", "AN", "THE", "WHAT", "WHICH", "WHO", "WHERE", "WHEN",
    "CSP", "DTE", "OTM", "ITM", "AI", "SEC", "ETF", "USD",
})

_COMPANY_STOPWORDS = frozenset({
    "what", "whats", "the", "a", "an", "for", "of", "and", "or", "to",
    "is", "are", "was", "me", "my", "i", "we", "you", "it", "this", "that",
    "latest", "recent", "news", "headline", "headlines", "stock", "stocks",
    "option", "options", "put", "puts", "call", "calls", "premium", "premiums",
    "secured", "cash", "csp", "chain", "delta", "strike", "dte", "otm", "itm",
    "show", "give", "tell", "about", "with", "from", "how", "much", "many",
    "please", "can", "could", "would", "should", "just", "any", "some",
    "available", "current", "today", "now", "week", "weekly", "monthly",
    "contract", "contracts", "quote", "quotes", "price", "prices",
    "compare", "versus", "screen", "these", "those", "ticker", "tickers",
    "candidate", "candidates", "idea", "ideas", "trade", "trades",
    "analyze", "analysis", "review", "explain", "does", "identify",
    "investigate", "evidence", "limit", "limits", "result", "research",
    "filing", "filings", "disclosure", "disclosures", "company", "companies",
    "risk", "risks", "hello", "hi", "based", "under", "over",
    "jan", "january", "feb", "february", "mar", "march", "apr", "april",
    "may", "jun", "june", "jul", "july", "aug", "august", "sep", "sept",
    "september", "oct", "october", "nov", "november", "dec", "december",
})

_NAME_CONNECTORS = frozenset({"of", "and", "the", "&"})

_MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sept": 9, "sep": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}


def parse_budget(question: str) -> float | None:
    """Extract an explicit dollar budget or capital amount from user text."""
    match = re.search(
        r"\$\s*([0-9][0-9,]*(?:\.\d+)?)\s*([kK]?)", question
    ) or re.search(
        r"(?:capital|budget)(?:\s+of|\s+is)?\s*\$?\s*"
        r"([0-9][0-9,]*(?:\.\d+)?)\s*([kK]?)",
        question,
        re.IGNORECASE,
    )
    if not match:
        return None
    value = float(match.group(1).replace(",", ""))
    return value * 1_000 if match.group(2).lower() == "k" else value


def parse_requested_count(question: str, *, default: int = 3, maximum: int = 5) -> int:
    """Extract a bounded candidate count from natural-language discovery requests."""
    words = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    }
    match = re.search(
        r"\b(?:top\s+)?(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+"
        r"(?:stocks?|tickers?|candidates?|ideas?|trades?)\b",
        question,
        re.IGNORECASE,
    )
    if not match:
        return default
    token = match.group(1).lower()
    count = words.get(token, int(token) if token.isdigit() else default)
    return max(1, min(count, maximum))


def extract_mentioned_tickers(question: str) -> list[str]:
    """Return ALL-CAPS or $cashtag tickers named in the question, in order."""
    cashtags = [
        token.upper()
        for token in re.findall(r"\$([A-Za-z][A-Za-z.\-]{0,9})\b", question)
    ]
    uppercase = re.findall(r"\b[A-Z]{1,5}\b", question)
    ordered: list[str] = []
    for token in [*cashtags, *uppercase]:
        ticker = token.upper()
        if ticker in _IGNORED_TICKERS or ticker in ordered:
            continue
        if not re.fullmatch(r"[A-Z][A-Z.\-]{0,9}", ticker):
            continue
        ordered.append(ticker)
    return ordered[:5]


def extract_company_names(question: str) -> list[str]:
    """Return proper company names for Alpaca ticker lookup. News queries stay raw."""
    cleaned = re.sub(r"[’']s\b", "", question)
    tokens = re.findall(r"[A-Za-z][A-Za-z.&-]*", cleaned)
    names: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if not _is_name_token(token):
            index += 1
            continue
        parts = [token]
        cursor = index + 1
        while cursor < len(tokens):
            nxt = tokens[cursor]
            lower = nxt.lower()
            if (
                lower in _NAME_CONNECTORS
                and cursor + 1 < len(tokens)
                and _is_name_token(tokens[cursor + 1])
            ):
                parts.extend([nxt, tokens[cursor + 1]])
                cursor += 2
                continue
            if _is_name_token(nxt):
                parts.append(nxt)
                cursor += 1
                continue
            break
        name = " ".join(parts)
        if name not in names:
            names.append(name)
        index = cursor
    return names[:5]


def parse_expiration_date(question: str, *, today: date | None = None) -> date | None:
    """Parse a contract expiration from US dates such as 09/04 or Sep 4."""
    today = today or date.today()
    numeric = re.search(
        r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", question
    )
    if numeric:
        parsed = _safe_date(
            _coerce_year(numeric.group(3), int(numeric.group(1)), int(numeric.group(2)), today),
            int(numeric.group(1)),
            int(numeric.group(2)),
        )
        if parsed:
            return parsed
    iso = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", question)
    if iso:
        parsed = _safe_date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        if parsed:
            return parsed
    named = re.search(
        r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
        r"jul(?:y)?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|"
        r"dec(?:ember)?)\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(\d{4}))?\b",
        question,
        re.IGNORECASE,
    )
    if named:
        month = _MONTHS[named.group(1).lower()]
        day = int(named.group(2))
        parsed = _safe_date(_coerce_year(named.group(3), month, day, today), month, day)
        if parsed:
            return parsed
    return None


_LOWERCASE_NAME_STOPWORDS = _COMPANY_STOPWORDS | {
    "want", "wanted", "need", "needed", "have", "has", "had", "get", "got",
    "looking", "look", "find", "give", "top", "best", "good", "great",
    "medium", "low", "high", "capital", "dollar", "dollars", "now",
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "also", "into", "only", "more", "most", "than", "then", "when",
    "which", "there", "here", "been", "being", "will", "make", "know",
    "think", "still", "same", "other", "after", "before", "between",
    "through", "without", "within", "using", "used", "currently",
}


def _is_name_token(token: str) -> bool:
    lower = token.lower()
    if lower in _COMPANY_STOPWORDS:
        return False
    if token.isupper() and len(token) <= 5:
        return False
    if token[0].isupper():
        return True
    if lower in _LOWERCASE_NAME_STOPWORDS:
        return False
    return len(token) >= 4


def _valid_month_day(month: int, day: int) -> bool:
    return 1 <= month <= 12 and 1 <= day <= 31


def _safe_date(year: int | None, month: int, day: int) -> date | None:
    if year is None or not _valid_month_day(month, day):
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _coerce_year(year_token: str | None, month: int, day: int, today: date) -> int | None:
    if year_token:
        year = int(year_token)
        return year + 2000 if year < 100 else year
    candidate = _safe_date(today.year, month, day)
    if candidate is None:
        return None
    return today.year if candidate >= today else today.year + 1
