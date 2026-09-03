from __future__ import annotations

import json

from csp_screener.providers import supabase


class Response:
    def __init__(self, payload: object | None) -> None:
        self.payload = payload

    def __enter__(self) -> "Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode() if self.payload is not None else b""


def test_latest_screen_uses_server_credentials_and_returns_payload(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return Response([{"payload": {"candidates": ["AAPL"]}}])

    monkeypatch.setattr(supabase, "urlopen", fake_urlopen)
    store = supabase.SupabaseStateStore(
        "https://example.supabase.co/", "service-secret", timeout=3
    )

    result = store.latest_screen(research=True)

    assert result == {"candidates": ["AAPL"]}
    assert captured["timeout"] == 3
    request = captured["request"]
    assert request.full_url.startswith(
        "https://example.supabase.co/rest/v1/dashboard_snapshots?"
    )
    assert "research=eq.true" in request.full_url
    assert request.get_header("Apikey") == "service-secret"
    assert request.get_header("Authorization") == "Bearer service-secret"


def test_save_research_posts_expected_record(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        return Response(None)

    monkeypatch.setattr(supabase, "urlopen", fake_urlopen)
    store = supabase.SupabaseStateStore("https://example.supabase.co", "secret")

    store.save_research("MU", "Why MU?", {"answer": "Example"})

    request = captured["request"]
    assert request.method == "POST"
    assert request.full_url.endswith("/rest/v1/research_runs")
    assert json.loads(request.data) == {
        "symbol": "MU",
        "question": "Why MU?",
        "response": {"answer": "Example"},
    }
