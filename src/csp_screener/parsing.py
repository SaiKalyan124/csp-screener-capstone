from __future__ import annotations

import re


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
