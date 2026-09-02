import pytest

from csp_screener.providers import yahoo_mcp


def test_yahoo_mcp_client_uses_structured_tool_result(monkeypatch) -> None:
    async def fake_call_tool(name, arguments):
        assert name == "get_company_evidence"
        assert arguments["symbol"] == "MU"
        return ([], {"symbol": "MU", "filings": [], "news": []})

    monkeypatch.setattr(yahoo_mcp.mcp, "call_tool", fake_call_tool)
    result = yahoo_mcp.YahooFinanceMCPClient().company_evidence("MU")
    assert result["symbol"] == "MU"


def test_yahoo_mcp_client_rejects_invalid_tool_result(monkeypatch) -> None:
    async def fake_call_tool(name, arguments):
        return []

    monkeypatch.setattr(yahoo_mcp.mcp, "call_tool", fake_call_tool)
    with pytest.raises(RuntimeError, match="invalid result"):
        yahoo_mcp.YahooFinanceMCPClient().company_evidence("MU")
