import pytest

from csp_screener.mcp_servers import tavily as tavily_server
from csp_screener.providers import tavily_mcp


def test_tavily_mcp_client_uses_structured_tool_result(monkeypatch) -> None:
    async def fake_call_tool(name, arguments):
        assert name == "search_news"
        assert arguments["query"] == "What is the latest news of Apple?"
        return ([], {
            "query": arguments["query"],
            "news": [{"type": "News", "title": "Headline", "url": "https://example.test/aapl"}],
            "source": "Tavily via local MCP",
        })

    monkeypatch.setattr(tavily_mcp.mcp, "call_tool", fake_call_tool)
    result = tavily_mcp.TavilyMCPClient().search_news("What is the latest news of Apple?")
    assert result["news"][0]["url"] == "https://example.test/aapl"


def test_tavily_mcp_client_rejects_invalid_tool_result(monkeypatch) -> None:
    async def fake_call_tool(name, arguments):
        return []

    monkeypatch.setattr(tavily_mcp.mcp, "call_tool", fake_call_tool)
    with pytest.raises(RuntimeError, match="invalid result"):
        tavily_mcp.TavilyMCPClient().search_news("latest news")


def test_tavily_search_returns_warning_without_api_key(monkeypatch) -> None:
    monkeypatch.setattr(tavily_server, "load_env_files", lambda: None)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    result = tavily_server._search_news("What is the latest news of Apple?")
    assert result["news"] == []
    assert result["query"] == "What is the latest news of Apple?"
    assert result["error"] == "TAVILY_API_KEY is not configured"


def test_tavily_search_uses_certifi_and_keeps_snippets(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return (
                b'{"results":[{"title":"Apple names new CEO","url":'
                b'"https://example.test/apple","content":"John Ternus succeeds Tim Cook."}]}'
            )

    def fake_urlopen(request, timeout=15, context=None):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["context"] = context
        return FakeResponse()

    monkeypatch.setattr(tavily_server, "load_env_files", lambda: None)
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    monkeypatch.setattr(tavily_server.urllib.request, "urlopen", fake_urlopen)
    result = tavily_server._search_news("What is the latest news of Apple?")
    assert captured["url"] == tavily_server.TAVILY_SEARCH_URL
    assert captured["context"] is not None
    assert result["query"] == "What is the latest news of Apple?"
    assert result["news"][0]["title"] == "Apple names new CEO"
    assert result["news"][0]["summary"] == "John Ternus succeeds Tim Cook."
