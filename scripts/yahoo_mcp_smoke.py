from __future__ import annotations

import json

from csp_screener.providers import YahooFinanceMCPClient


def main() -> None:
    result = YahooFinanceMCPClient().company_evidence(
        "MU", filing_limit=2, news_limit=1
    )
    print(json.dumps({
        "symbol": result.get("symbol"),
        "filings": len(result.get("filings", [])),
        "news": len(result.get("news", [])),
        "source": result.get("source"),
    }))


if __name__ == "__main__":
    main()
