from __future__ import annotations

import json
import re
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .config import WEB_ROOT, load_settings
from .services import ApplicationService


SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


class DemoHandler(SimpleHTTPRequestHandler):
    """HTTP transport only; business logic lives in ApplicationService."""

    service: ApplicationService

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        try:
            if parsed.path == "/api/screen":
                force = query.get("refresh", ["0"])[0].lower() in {"1", "true", "yes"}
                self._send_json(self.service.screen(force=force))
                return
            if parsed.path == "/api/options":
                symbol = query.get("symbol", [""])[0].strip().upper()
                if not SYMBOL_RE.fullmatch(symbol):
                    self._send_json({"error": "Enter a valid ticker symbol."}, HTTPStatus.BAD_REQUEST)
                    return
                self._send_json(self.service.options(symbol))
                return
            super().do_GET()
        except Exception as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_GATEWAY)

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        if urlparse(self.path).path != "/api/chat":
            self._send_json({"error": "Not found."}, HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            symbol = str(payload.get("symbol", "")).strip().upper()
            question = str(payload.get("question", "")).strip()
            if not SYMBOL_RE.fullmatch(symbol):
                self._send_json({"error": "Enter a valid ticker symbol."}, HTTPStatus.BAD_REQUEST)
                return
            if not question:
                self._send_json({"error": "Question is required."}, HTTPStatus.BAD_REQUEST)
                return
            self._send_json(self.service.research(symbol, question))
        except (ValueError, json.JSONDecodeError):
            self._send_json({"error": "Invalid JSON request."}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_GATEWAY)

    def _send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        print(f"[http] {self.address_string()} {format % args}")


DemoService = ApplicationService


def main() -> None:
    settings = load_settings()
    service = ApplicationService(settings)
    DemoHandler.service = service
    server = ThreadingHTTPServer((settings.host, settings.port), DemoHandler)
    service.start_background_refresh()
    print(f"CSP demo running at http://{settings.host}:{settings.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        service.stop_background_refresh()
        server.server_close()


if __name__ == "__main__":
    main()
