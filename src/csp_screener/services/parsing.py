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
