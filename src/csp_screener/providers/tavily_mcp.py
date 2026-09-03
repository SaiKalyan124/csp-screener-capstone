from __future__ import annotations

import json
import os
from typing import Any

import anyio
from langchain_mcp_adapters.client import MultiServerMCPClient


class TavilyMCPClient:
    """Bounded adapter for Tavily's hosted streamable-HTTP MCP server."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv("TAVILY_API_KEY")

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def _search_async(self, symbol: str, limit: int) -> list[dict[str, Any]]:
        if not self.api_key:
            return []
        client = MultiServerMCPClient({
            "tavily": {
                "transport": "streamable_http",
                "url": "https://mcp.tavily.com/mcp/",
                "headers": {"Authorization": f"Bearer {self.api_key}"},
            }
        })
        tools = await client.get_tools(server_name="tavily")
        search = next((tool for tool in tools if "search" in tool.name.lower()), None)
        if search is None:
            raise RuntimeError("Tavily MCP search tool is unavailable")
        result = await search.ainvoke({
            "query": f"{symbol} company latest material news earnings risks",
            # The hosted MCP tool currently exposes the general-search topic.
            # The query itself constrains results to recent company news.
            "topic": "general",
            "search_depth": "advanced",
            "max_results": min(max(limit, 1), 5),
            "include_raw_content": False,
        })
        return self._normalize(result, symbol, limit)

    @staticmethod
    def _normalize(result: Any, symbol: str, limit: int) -> list[dict[str, Any]]:
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except json.JSONDecodeError:
                return []
        if isinstance(result, list):
            for item in result:
                content = (
                    item.get("text") if isinstance(item, dict)
                    else getattr(item, "content", None) or getattr(item, "text", None)
                )
                if content:
                    return TavilyMCPClient._normalize(content, symbol, limit)
            rows = result
        elif isinstance(result, dict):
            rows = result.get("results") or result.get("data") or []
        else:
            rows = []
        normalized = []
        for row in rows:
            if not isinstance(row, dict) or not row.get("title") or not row.get("url"):
                continue
            normalized.append({
                "type": "Web research",
                "date": row.get("published_date") or row.get("publishedDate"),
                "title": row["title"],
                "url": row["url"],
                "summary": row.get("content") or row.get("snippet"),
                "symbol": symbol,
                "source": "Tavily via remote MCP",
            })
            if len(normalized) >= limit:
                break
        return normalized

    def company_news(self, symbol: str, limit: int = 3) -> list[dict[str, Any]]:
        return anyio.run(self._search_async, symbol.strip().upper(), limit)
