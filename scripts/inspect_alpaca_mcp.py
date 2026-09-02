from __future__ import annotations

import anyio
import os

from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def inspect_tools() -> None:
    load_dotenv()
    params = StdioServerParameters(
        command="uvx",
        args=["alpaca-mcp-server"],
        env={
            "ALPACA_API_KEY": os.environ["ALPACA_API_KEY"],
            "ALPACA_SECRET_KEY": os.environ["ALPACA_SECRET_KEY"],
            "ALPACA_PAPER_TRADE": "true",
            "ALPACA_TOOLSETS": "assets,stock-data,options-data,news",
        },
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            wanted = {
                "get_stock_bars",
                "get_stock_latest_trade",
                "get_option_chain",
            }
            for tool in tools.tools:
                if tool.name in wanted:
                    print(tool.model_dump_json(exclude_none=True), flush=True)
            trade = await session.call_tool(
                "get_stock_latest_trade", {"symbols": "MU", "feed": "iex"}
            )
            chain = await session.call_tool("get_option_chain", {
                "underlying_symbol": "MU",
                "feed": "indicative",
                "limit": 2,
                "type": "put",
            })
            print("TRADE=" + repr(trade.structuredContent), flush=True)
            print("CHAIN=" + repr(chain.structuredContent), flush=True)


if __name__ == "__main__":
    anyio.run(inspect_tools)
