from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from typing import Any

import certifi
from mcp.server.fastmcp import FastMCP

from ..config import load_env_files

mcp = FastMCP("csp-tavily-news")

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
_MAX_RESULTS = 8
_SUMMARY_CHARS = 400


def _ssl_context() -> ssl.SSLContext:
    """Use certifi so Tavily HTTPS works on macOS Python builds."""
    return ssl.create_default_context(cafile=certifi.where())


def _search_news(query: str, max_results: int = 5) -> dict[str, Any]:
    """Search Tavily with the user's question as written. Do not rewrite tickers."""
    search_query = query.strip()
    limit = max(1, min(int(max_results), _MAX_RESULTS))
    load_env_files()
    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not search_query:
        return {
            "query": "",
            "news": [],
            "source": "Tavily via local MCP",
            "error": "Question is required",
        }
    if not api_key:
        return {
            "query": search_query,
            "news": [],
            "source": "Tavily via local MCP",
            "error": "TAVILY_API_KEY is not configured",
        }

    payload = json.dumps({
        "api_key": api_key,
        "query": search_query,
        "topic": "news",
        "search_depth": "basic",
        "max_results": limit,
        "include_answer": False,
    }).encode("utf-8")
    request = urllib.request.Request(
        TAVILY_SEARCH_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15, context=_ssl_context()) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        return {
            "query": search_query,
            "news": [],
            "source": "Tavily via local MCP",
            "error": f"{type(exc).__name__}: {type(reason).__name__}",
        }

    news: list[dict[str, Any]] = []
    for item in body.get("results") or []:
        if not isinstance(item, dict):
            continue
        title = item.get("title")
        url = item.get("url")
        if not title or not url:
            continue
        summary = item.get("content")
        row: dict[str, Any] = {
            "type": "News",
            "date": item.get("published_date") or item.get("publishedDate"),
            "title": title,
            "url": url,
        }
        if isinstance(summary, str) and summary.strip():
            row["summary"] = summary.strip()[:_SUMMARY_CHARS]
        news.append(row)
        if len(news) >= limit:
            break
    return {
        "query": search_query,
        "news": news,
        "source": "Tavily via local MCP",
    }


@mcp.tool()
def search_news(query: str, max_results: int = 5) -> dict[str, Any]:
    """Return bounded Tavily news hits for the user's question text."""
    return _search_news(query, max_results)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
