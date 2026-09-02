from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("csp-yahoo-research")


def _company_evidence(
    symbol: str,
    filing_limit: int = 5,
    news_limit: int = 3,
) -> dict[str, Any]:
    import yfinance as yf

    ticker_symbol = symbol.strip().upper()
    ticker = yf.Ticker(ticker_symbol)
    filings = ticker.get_sec_filings() or []
    if isinstance(filings, dict):
        filings = filings.get("filings") or filings.get("data") or []
    normalized_filings = []
    for item in filings:
        if not isinstance(item, dict):
            continue
        normalized_filings.append({
            "type": item.get("type") or item.get("formType") or item.get("form"),
            "date": item.get("date") or item.get("filingDate"),
            "title": item.get("title") or item.get("description"),
            "url": item.get("edgarUrl") or item.get("url"),
        })
        if len(normalized_filings) >= filing_limit:
            break

    normalized_news = []
    if news_limit:
        try:
            news = ticker.news or []
        except Exception:
            news = []
        for item in news:
            content = item.get("content", item) if isinstance(item, dict) else {}
            canonical = content.get("canonicalUrl") or {}
            url = canonical.get("url") if isinstance(canonical, dict) else None
            url = url or content.get("link")
            title = content.get("title")
            if title and url:
                normalized_news.append({
                    "type": "News",
                    "date": content.get("pubDate"),
                    "title": title,
                    "url": url,
                })
            if len(normalized_news) >= news_limit:
                break

    return {
        "symbol": ticker_symbol,
        "filings": normalized_filings,
        "news": normalized_news,
        "source": "Yahoo Finance via local MCP",
    }


@mcp.tool()
def get_company_evidence(
    symbol: str,
    filing_limit: int = 5,
    news_limit: int = 3,
) -> dict[str, Any]:
    """Return normalized SEC-filing metadata and news for one ticker."""
    return _company_evidence(symbol, filing_limit, news_limit)


@mcp.tool()
def get_company_evidence_batch(
    symbols: list[str],
    filing_limit: int = 2,
    news_limit: int = 3,
) -> dict[str, Any]:
    """Return bounded Yahoo research evidence for up to ten tickers."""
    bounded = list(dict.fromkeys(symbol.strip().upper() for symbol in symbols))[:10]
    evidence: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=min(5, len(bounded) or 1)) as pool:
        futures = {
            pool.submit(_company_evidence, symbol, filing_limit, news_limit): symbol
            for symbol in bounded
        }
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                evidence[symbol] = future.result()
            except Exception as exc:
                errors[symbol] = type(exc).__name__
    return {"evidence": evidence, "errors": errors}


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
