from __future__ import annotations

from typing import Any

import anyio
import json

from ..mcp_servers.yahoo_finance import mcp


class YahooFinanceMCPClient:
    """Typed application adapter for the local Yahoo Finance MCP server."""

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
            f"Yahoo MCP tool {tool} returned an invalid result: {result!r}"
        )

    def _call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return anyio.run(self._call_async, tool, arguments)

    def company_evidence(
        self,
        symbol: str,
        *,
        filing_limit: int = 5,
        news_limit: int = 0,
    ) -> dict[str, Any]:
        return self._call("get_company_evidence", {
            "symbol": symbol,
            "filing_limit": filing_limit,
            "news_limit": news_limit,
        })

    def company_evidence_batch(
        self,
        symbols: list[str],
        *,
        filing_limit: int = 2,
        news_limit: int = 3,
    ) -> dict[str, Any]:
        return self._call("get_company_evidence_batch", {
            "symbols": symbols,
            "filing_limit": filing_limit,
            "news_limit": news_limit,
        })

    def next_earnings_date(self, symbol: str) -> dict[str, Any]:
        return self._call("get_next_earnings_date", {"symbol": symbol})
