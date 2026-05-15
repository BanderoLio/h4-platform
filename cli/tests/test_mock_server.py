from __future__ import annotations

import json
import threading
import unittest
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import error, request

from agent_scan_cli.mock_server import MockScanHandler, MockScanServer


class MockServerTests(unittest.TestCase):
    def test_start_returns_202_and_report_returns_json_when_done(self) -> None:
        with _running_server(report_delay=0) as base_url:
            status, body = _post_json(f"{base_url}/scan/start", {"repo_url": "https://github.com/org/repo"})
            scan_id = body["scan_id"]
            report_status, report_body = _get_json(f"{base_url}/scan/{scan_id}/report")

        self.assertEqual(status, 202)
        self.assertEqual(report_status, 200)
        self.assertEqual(report_body["status"], "done")
        self.assertIn("Repository Scan Report", report_body["report"])
        self.assertIn("https://github.com/org/repo", report_body["report"])

    def test_report_running_returns_202(self) -> None:
        with _running_server(report_delay=60) as base_url:
            _status, body = _post_json(f"{base_url}/scan/start", {"repo_url": "https://github.com/org/repo"})
            scan_id = body["scan_id"]
            report_status, report_body = _get_json(f"{base_url}/scan/{scan_id}/report")

        self.assertEqual(report_status, 202)
        self.assertEqual(report_body, {"status": "running", "report": None})

    def test_unknown_scan_returns_404(self) -> None:
        with _running_server(report_delay=0) as base_url:
            with self.assertRaises(error.HTTPError) as exc:
                request.urlopen(f"{base_url}/scan/missing/report", timeout=5)
            body = json.loads(exc.exception.read().decode("utf-8"))
            exc.exception.close()

        self.assertEqual(exc.exception.code, 404)
        self.assertEqual(body, {"detail": "scan not found"})

    def test_start_requires_repo_url(self) -> None:
        with _running_server(report_delay=0) as base_url:
            with self.assertRaises(error.HTTPError) as exc:
                _post_json(f"{base_url}/scan/start", {})
            exc.exception.close()

        self.assertEqual(exc.exception.code, 400)

    def test_webhook_receives_report_when_done(self) -> None:
        with _webhook_server() as webhook:
            with _running_server(report_delay=0) as base_url:
                _status, body = _post_json(
                    f"{base_url}/scan/start",
                    {
                        "repo_url": "https://github.com/org/repo",
                        "webhook_url": webhook.url,
                    },
                )

                self.assertTrue(webhook.event.wait(timeout=5))

        self.assertEqual(webhook.payload["scan_id"], body["scan_id"])
        self.assertIn("Repository Scan Report", webhook.payload["report"])


class _running_server:
    def __init__(self, *, report_delay: float) -> None:
        self._server = MockScanServer(("127.0.0.1", 0), MockScanHandler, report_delay=report_delay)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> str:
        self._thread.start()
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    def __exit__(self, *args: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def _post_json(url: str, payload: dict[str, object]) -> tuple[int, dict[str, object]]:
    req = request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def _get_json(url: str) -> tuple[int, dict[str, object]]:
    with request.urlopen(url, timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


class _webhook_server:
    def __init__(self) -> None:
        self.event = threading.Event()
        self.payload: dict[str, object] = {}
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        host, port = self._server.server_address
        self.url = f"http://{host}:{port}/webhook"

    def __enter__(self) -> "_webhook_server":
        self._thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        owner = self

        class WebhookHandler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                size = int(self.headers.get("Content-Length", "0"))
                owner.payload = json.loads(self.rfile.read(size).decode("utf-8"))
                owner.event.set()
                self.send_response(HTTPStatus.OK)
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:
                return

        return WebhookHandler


if __name__ == "__main__":
    unittest.main()
