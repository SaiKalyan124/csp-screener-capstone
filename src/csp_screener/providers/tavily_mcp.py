from __future__ import annotations

from typing import Any

import anyio
import json

from ..mcp_servers.tavily import mcp


class TavilyMCPClient:
    """Typed application adapter for the local Tavily news MCP server."""

    async def _call_async(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = await mcp.call_tool(tool, arguments)
        if isinstance(result, dict):
            return result
        if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], dict):
            return result[1]
        for item in result[0] if isinstance(result, tuple) else result:
            text = getattr(item, "text", None)
            if text:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    return parsed
        raise RuntimeError(
            f"Tavily MCP tool {tool} returned an invalid result: {result!r}"
        )

    def _call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return anyio.run(self._call_async, tool, arguments)

    def search_news(self, query: str, *, max_results: int = 5) -> dict[str, Any]:
        return self._call("search_news", {
            "query": query,
            "max_results": max_results,
        })
