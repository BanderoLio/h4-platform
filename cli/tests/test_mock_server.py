from __future__ import annotations

import json
import threading
import unittest
from urllib import error, request

from cli.src.agent_scan_cli.mock_server import MockScanHandler, MockScanServer


class MockServerTests(unittest.TestCase):
    def test_report_is_404_before_delay_and_text_after_delay(self) -> None:
        with _running_server(report_delay=0) as base_url:
            scan_id = _post_json(f"{base_url}/scan/start", {"repo_url": "https://github.com/org/repo"})["scan_id"]
            report = request.urlopen(f"{base_url}/scan/{scan_id}/report", timeout=5).read().decode("utf-8")

        self.assertIn("Repository Scan Report", report)
        self.assertIn("https://github.com/org/repo", report)

    def test_report_not_ready_returns_404(self) -> None:
        with _running_server(report_delay=60) as base_url:
            scan_id = _post_json(f"{base_url}/scan/start", {"repo_url": "https://github.com/org/repo"})["scan_id"]

            with self.assertRaises(error.HTTPError) as exc:
                request.urlopen(f"{base_url}/scan/{scan_id}/report", timeout=5)
            exc.exception.close()

        self.assertEqual(exc.exception.code, 404)

    def test_start_requires_repo_url(self) -> None:
        with _running_server(report_delay=0) as base_url:
            with self.assertRaises(error.HTTPError) as exc:
                _post_json(f"{base_url}/scan/start", {})
            exc.exception.close()

        self.assertEqual(exc.exception.code, 400)


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


def _post_json(url: str, payload: dict[str, object]) -> dict[str, object]:
    req = request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return json.loads(request.urlopen(req, timeout=5).read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
