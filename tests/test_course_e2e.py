from csp_screener.course_e2e import _normalize_filings


def test_normalize_yahoo_filing_metadata() -> None:
    raw = {
        "filings": [
            {
                "type": "10-Q",
                "date": "2026-06-25",
                "title": "Periodic Financial Reports",
                "edgarUrl": "https://example.test/filing",
            }
        ]
    }

    assert _normalize_filings(raw) == [
        {
            "type": "10-Q",
            "date": "2026-06-25",
            "title": "Periodic Financial Reports",
            "url": "https://example.test/filing",
        }
    ]


def test_normalize_limits_and_ignores_invalid_items() -> None:
    raw = [{"formType": "8-K", "filingDate": str(i)} for i in range(5)]
    raw.insert(1, "invalid")

    assert len(_normalize_filings(raw, limit=3)) == 3
