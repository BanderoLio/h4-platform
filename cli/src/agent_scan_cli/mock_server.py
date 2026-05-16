from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib import error, request
from urllib.parse import unquote, urlparse


@dataclass(frozen=True)
class ScanRecord:
    scan_id: str
    repo_url: str
    webhook_url: str | None
    created_at: float
    ready_at: float


class ScanStore:
    def __init__(self, report_delay: float) -> None:
        self._report_delay = report_delay
        self._records: dict[str, ScanRecord] = {}
        self._lock = threading.Lock()

    def start(self, repo_url: str, *, webhook_url: str | None = None) -> ScanRecord:
        now = time.monotonic()
        scan_id = uuid.uuid4().hex
        record = ScanRecord(
            scan_id=scan_id,
            repo_url=repo_url,
            webhook_url=webhook_url,
            created_at=now,
            ready_at=now + self._report_delay,
        )
        with self._lock:
            self._records[scan_id] = record
        return record

    def get(self, scan_id: str) -> ScanRecord | None:
        with self._lock:
            return self._records.get(scan_id)

    @staticmethod
    def is_ready(record: ScanRecord) -> bool:
        return time.monotonic() >= record.ready_at


class MockScanServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        *,
        report_delay: float,
    ) -> None:
        super().__init__(server_address, handler_class)
        self.store = ScanStore(report_delay)

    def schedule_webhook(self, record: ScanRecord) -> None:
        delay = max(0.0, record.ready_at - time.monotonic())
        thread = threading.Thread(target=self._send_webhook_after_delay, args=(record, delay), daemon=True)
        thread.start()

    def _send_webhook_after_delay(self, record: ScanRecord, delay: float) -> None:
        time.sleep(delay)
        if not record.webhook_url:
            return

        payload = json.dumps({"scan_id": record.scan_id, "report": _build_report(record)}).encode("utf-8")
        req = request.Request(
            record.webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            request.urlopen(req, timeout=10).close()
        except (error.URLError, TimeoutError) as exc:
            sys.stderr.write(f"Webhook delivery failed for {record.scan_id}: {exc}\n")


class MockScanHandler(BaseHTTPRequestHandler):
    server: MockScanServer

    def do_POST(self) -> None:
        if self.path != "/scan/start":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return

        try:
            payload = self._read_json()
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return

        repo_url = payload.get("repo_url")
        if not isinstance(repo_url, str) or not repo_url.strip():
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "repo_url is required"})
            return
        webhook_url = payload.get("webhook_url")
        if webhook_url is not None and (not isinstance(webhook_url, str) or not webhook_url.strip()):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "webhook_url must be a non-empty string"})
            return

        record = self.server.store.start(
            repo_url.strip(),
            webhook_url=webhook_url.strip() if isinstance(webhook_url, str) else None,
        )
        if record.webhook_url:
            self.server.schedule_webhook(record)

        self._send_json(
            HTTPStatus.ACCEPTED,
            {"scan_id": record.scan_id},
        )

    def do_GET(self) -> None:
        scan_id = _scan_id_from_report_path(self.path)
        if scan_id is None:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return

        record = self.server.store.get(scan_id)
        if record is None:
            self._send_json(HTTPStatus.NOT_FOUND, {"detail": "scan not found"})
            return

        if not self.server.store.is_ready(record):
            self._send_json(HTTPStatus.ACCEPTED, {"status": "running", "report": None})
            return

        self._send_json(HTTPStatus.OK, {"status": "done", "report": _build_report(record)})

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write(f"{self.address_string()} - {format % args}\n")

    def _read_json(self) -> dict[str, Any]:
        content_length = self.headers.get("Content-Length")
        if content_length is None:
            raise ValueError("request body is required")

        try:
            size = int(content_length)
        except ValueError as exc:
            raise ValueError("invalid Content-Length") from exc

        try:
            data = json.loads(self.rfile.read(size).decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("request body must be JSON") from exc

        if not isinstance(data, dict):
            raise ValueError("request body must be a JSON object")
        return data

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-scan-mock-server",
        description="Run a local mock server for the repository scan API.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind.")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind.")
    parser.add_argument(
        "--delay",
        type=float,
        default=3.0,
        help="Seconds before a created report becomes available.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    server = MockScanServer((args.host, args.port), MockScanHandler, report_delay=args.delay)
    host, port = server.server_address

    print(f"Mock scan server listening on http://{host}:{port}", file=sys.stderr)
    print(f"Reports become ready after {args.delay:g}s", file=sys.stderr)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping mock scan server.", file=sys.stderr)
    finally:
        server.server_close()
    return 0


def _scan_id_from_report_path(path: str) -> str | None:
    parsed = urlparse(path)
    parts = parsed.path.strip("/").split("/")
    if len(parts) == 3 and parts[0] == "scan" and parts[2] == "report":
        return unquote(parts[1])
    return None


def _build_report(record: ScanRecord) -> str:
    return "\n".join(
        [
            "Repository Scan Report",
            "======================",
            "",
            f"Scan id: {record.scan_id}",
            f"Repository: {record.repo_url}",
            "",
            "Summary:",
            "- Mock report generated successfully.",
            "- No real repository analysis was performed.",
            "- The API contract is ready for CLI integration tests.",
            "",
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
