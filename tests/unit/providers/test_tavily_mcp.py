from csp_screener.providers.tavily_mcp import TavilyMCPClient
import json


def test_tavily_is_optional_without_api_key(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    assert not TavilyMCPClient().configured


def test_tavily_normalizes_bounded_search_results():
    result = TavilyMCPClient._normalize(
        {
            "results": [
                {
                    "title": "Apple announces material update",
                    "url": "https://example.test/apple",
                    "content": "A short research summary.",
                    "published_date": "2026-09-02",
                },
                {"title": "Missing URL"},
            ]
        },
        "AAPL",
        2,
    )

    assert result == [
        {
            "type": "Web research",
            "date": "2026-09-02",
            "title": "Apple announces material update",
            "url": "https://example.test/apple",
            "summary": "A short research summary.",
            "symbol": "AAPL",
            "source": "Tavily via remote MCP",
        }
    ]


def test_tavily_normalizes_mcp_text_content_block():
    result = TavilyMCPClient._normalize(
        [{
            "type": "text",
            "text": json.dumps({
                "results": [{
                    "title": "Apple reports an update",
                    "url": "https://example.test/apple-update",
                    "content": "A bounded summary.",
                }]
            }),
        }],
        "AAPL",
        2,
    )

    assert len(result) == 1
    assert result[0]["symbol"] == "AAPL"
    assert result[0]["title"] == "Apple reports an update"
