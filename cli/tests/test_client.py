from __future__ import annotations

import json
import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from agent_scan_cli.client import ReportNotReady, ScanClient, ScanFailed, ScanNotFound, default_report_path


class ScanClientTests(unittest.TestCase):
    def test_start_scan_posts_repo_url_and_returns_scan_id(self) -> None:
        response = _response({"scan_id": "scan-123"}, status=202)

        with patch("agent_scan_cli.client.request.urlopen", return_value=response) as urlopen:
            scan_id = ScanClient("http://api.test").start_scan(
                "https://github.com/org/repo",
                webhook_url="https://hooks.test/report",
            )

        self.assertEqual(scan_id, "scan-123")
        req = urlopen.call_args.args[0]
        self.assertEqual(req.full_url, "http://api.test/scan/start")
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(
            json.loads(req.data.decode("utf-8")),
            {"repo_url": "https://github.com/org/repo", "webhook_url": "https://hooks.test/report"},
        )

    def test_get_report_maps_202_running_to_not_ready(self) -> None:
        response = _response({"status": "running", "report": None}, status=202)

        with patch("agent_scan_cli.client.request.urlopen", return_value=response):
            with self.assertRaises(ReportNotReady):
                ScanClient("http://api.test").get_report("a")

    def test_get_report_maps_404_to_scan_not_found(self) -> None:
        error = HTTPError(
            "http://api.test/scan/a/report",
            404,
            "Not Found",
            hdrs=None,
            fp=BytesIO(b'{"detail":"scan not found"}'),
        )

        with patch("agent_scan_cli.client.request.urlopen", side_effect=error):
            with self.assertRaises(ScanNotFound):
                ScanClient("http://api.test").get_report("a")

    def test_save_report_writes_text_file(self) -> None:
        response = _response({"status": "done", "report": "plain text report"}, status=200)

        with TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "report.txt"
            with patch("agent_scan_cli.client.request.urlopen", return_value=response):
                ScanClient("http://api.test").save_report("scan-123", output)

            self.assertEqual(output.read_text(), "plain text report")

    def test_failed_report_raises_scan_failed(self) -> None:
        response = _response({"status": "failed", "report": "clone failed"}, status=200)

        with patch("agent_scan_cli.client.request.urlopen", return_value=response):
            with self.assertRaisesRegex(ScanFailed, "clone failed"):
                ScanClient("http://api.test").get_report("scan-123")

    def test_default_report_path_sanitizes_scan_id(self) -> None:
        self.assertEqual(default_report_path("abc/123").name, "scan-report-abc_123.txt")


def _response(data: object, *, status: int) -> Mock:
    return _raw_response(json.dumps(data).encode("utf-8"), status=status)


def _raw_response(data: bytes, *, status: int) -> Mock:
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=None)
    response.read = Mock(return_value=data)
    response.status = status
    return response


if __name__ == "__main__":
    unittest.main()
