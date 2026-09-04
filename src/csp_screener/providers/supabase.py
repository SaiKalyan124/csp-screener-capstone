from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class SupabaseStateStore:
    """Small server-only REST adapter for durable hosted state."""

    def __init__(self, url: str, service_role_key: str, timeout: float = 8.0) -> None:
        self.base_url = url.rstrip("/") + "/rest/v1"
        self.timeout = timeout
        self.headers = {
            "apikey": service_role_key,
            "authorization": f"Bearer {service_role_key}",
            "content-type": "application/json",
        }

    def latest_screen(self, research: bool) -> dict[str, object] | None:
        query = urlencode(
            {
                "select": "payload",
                "research": f"eq.{str(research).lower()}",
                "order": "generated_at.desc",
                "limit": "1",
            }
        )
        rows = self._request("GET", f"dashboard_snapshots?{query}")
        if isinstance(rows, list) and rows:
            payload = rows[0].get("payload")
            return payload if isinstance(payload, dict) else None
        return None

    def save_screen(self, payload: dict[str, object], research: bool) -> None:
        generated_at = str(payload.get("generated_at") or datetime.now(timezone.utc).isoformat())
        self._request(
            "POST",
            "dashboard_snapshots",
            {"generated_at": generated_at, "research": research, "payload": payload},
        )

    def save_research(
        self, symbol: str, question: str, response: dict[str, object]
    ) -> None:
        self._request(
            "POST",
            "research_runs",
            {"symbol": symbol, "question": question, "response": response},
        )

    def _request(
        self, method: str, path: str, payload: dict[str, object] | None = None
    ) -> object:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {**self.headers, "prefer": "return=minimal"}
        request = Request(
            f"{self.base_url}/{path}", data=body, headers=headers, method=method
        )
        with urlopen(request, timeout=self.timeout) as response:
            data = response.read()
        return json.loads(data) if data else None


class SupabaseUsageQuota:
    """Authenticated REST adapter for atomic per-user AI budget reservations."""

    def __init__(self, url: str, anon_key: str, timeout: float = 8.0) -> None:
        self.rpc_url = url.rstrip("/") + "/rest/v1/rpc/consume_weekly_ai_budget"
        self.anon_key = anon_key
        self.timeout = timeout

    def reserve(
        self, access_token: str, estimated_cost_usd: float, weekly_limit_usd: float
    ) -> dict[str, object]:
        body = json.dumps({
            "p_estimated_cost_usd": estimated_cost_usd,
            "p_weekly_limit_usd": weekly_limit_usd,
        }).encode("utf-8")
        request = Request(
            self.rpc_url,
            data=body,
            headers={
                "apikey": self.anon_key,
                "authorization": f"Bearer {access_token}",
                "content-type": "application/json",
            },
            method="POST",
        )
        with urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read() or b"{}")
        if isinstance(payload, list):
            payload = payload[0] if payload else {}
        return payload if isinstance(payload, dict) else {}
