from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, request
from urllib.parse import quote


DEFAULT_BASE_URL = "http://localhost:8000"


class ScanApiError(RuntimeError):
    """Raised when the scan API returns an unexpected response."""


class ReportNotReady(ScanApiError):
    """Raised when the report endpoint returns 404."""


@dataclass(frozen=True)
class ScanClient:
    base_url: str = DEFAULT_BASE_URL
    timeout: float = 30.0

    def start_scan(self, repo_url: str) -> str:
        payload = json.dumps({"repo_url": repo_url}).encode("utf-8")
        response = self._request(
            "POST",
            "/scan/start",
            body=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )

        try:
            data = json.loads(response.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ScanApiError("POST /scan/start returned invalid JSON") from exc

        scan_id = _extract_scan_id(data)
        if not scan_id:
            raise ScanApiError("POST /scan/start response does not contain a scan id")
        return scan_id

    def get_report(self, scan_id: str) -> bytes:
        escaped_id = quote(scan_id, safe="")
        try:
            return self._request(
                "GET",
                f"/scan/{escaped_id}/report",
                headers={"Accept": "text/plain"},
            )
        except error.HTTPError as exc:
            if exc.code == 404:
                exc.close()
                raise ReportNotReady(f"Report for scan {scan_id} is not ready") from exc
            raise _api_error_from_http(exc) from exc

    def wait_for_report(
        self,
        scan_id: str,
        *,
        interval: float = 5.0,
        timeout: float | None = 600.0,
    ) -> bytes:
        started_at = time.monotonic()

        while True:
            try:
                return self.get_report(scan_id)
            except ReportNotReady:
                if timeout is not None and time.monotonic() - started_at >= timeout:
                    raise TimeoutError(f"Report for scan {scan_id} was not ready in time")
                time.sleep(interval)

    def save_report(self, scan_id: str, output: Path, *, wait: bool = False) -> Path:
        output.parent.mkdir(parents=True, exist_ok=True)
        report = self.wait_for_report(scan_id) if wait else self.get_report(scan_id)
        output.write_bytes(report)
        return output

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> bytes:
        url = f"{self.base_url.rstrip('/')}{path}"
        req = request.Request(url, data=body, headers=headers or {}, method=method)

        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                return response.read()
        except error.HTTPError:
            raise
        except error.URLError as exc:
            raise ScanApiError(f"Could not reach scan API at {url}: {exc.reason}") from exc


def default_report_path(scan_id: str) -> Path:
    safe_name = "".join(char if char.isalnum() or char in "-_." else "_" for char in scan_id)
    return Path(f"scan-report-{safe_name}.txt")


def _extract_scan_id(data: Any) -> str | None:
    if isinstance(data, str):
        return data
    if not isinstance(data, dict):
        return None

    for key in ("scan_id", "id", "dialog_id", "conversation_id"):
        value = data.get(key)
        if value is not None:
            return str(value)
    return None


def _api_error_from_http(exc: error.HTTPError) -> ScanApiError:
    details = exc.read().decode("utf-8", errors="replace").strip()
    suffix = f": {details}" if details else ""
    return ScanApiError(f"Scan API returned HTTP {exc.code}{suffix}")
