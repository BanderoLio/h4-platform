from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, request
from urllib.parse import quote


_HTTP_URL = re.compile(r"https?://", re.IGNORECASE)


DEFAULT_BASE_URL = "http://localhost:8000"


class ScanApiError(RuntimeError):
    """Raised when the scan API returns an unexpected response."""


class ScanAuthError(ScanApiError):
    """Raised when the scan API rejects the request for missing/invalid auth.

    HTTP 401 (wrong key) or 403 (no Authorization header at all).
    """


class ReportNotReady(ScanApiError):
    """Raised when the report endpoint returns 202 with a running status."""


class ScanNotFound(ScanApiError):
    """Raised when the scan API cannot find a scan id."""


class ScanFailed(ScanApiError):
    """Raised when a scan finishes with a failed status."""


@dataclass(frozen=True)
class ReportResponse:
    status: str
    report: str | None


@dataclass(frozen=True)
class ScanClient:
    base_url: str = DEFAULT_BASE_URL
    timeout: float = 30.0
    api_key: str | None = None

    def start_scan(self, repo: str, *, webhook_url: str | None = None) -> str:
        # interactive=False: this CLI has no resume command, so scans must run
        # to completion without pausing on clarify/gate prompts.
        # An http(s) value is cloned by the backend; anything else is treated
        # as a server-side local path (requires ALLOWED_LOCAL_ROOTS there).
        request_body: dict[str, Any] = {"interactive": False}
        repo = repo.strip()
        if _HTTP_URL.match(repo):
            request_body["repo_url"] = repo
        else:
            request_body["repo_path"] = repo
        if webhook_url:
            request_body["webhook_url"] = webhook_url

        payload = json.dumps(request_body).encode("utf-8")
        response = self._request_json(
            "POST",
            "/scan/start",
            body=payload,
            expected_statuses={202},
        )

        scan_id = _extract_scan_id(response.data)
        if not scan_id:
            raise ScanApiError("POST /scan/start response does not contain a scan id")
        return scan_id

    def get_report_status(self, scan_id: str) -> ReportResponse:
        escaped_id = quote(scan_id, safe="")
        response = self._request_json(
            "GET",
            f"/scan/{escaped_id}/report",
            headers={"Accept": "application/json"},
            expected_statuses={200, 202},
        )

        if not isinstance(response.data, dict):
            raise ScanApiError("GET report response must be a JSON object")

        status = response.data.get("status")
        report = response.data.get("report")
        if not isinstance(status, str):
            raise ScanApiError("GET report response does not contain a valid status")
        if report is not None and not isinstance(report, str):
            raise ScanApiError("GET report response contains a non-text report")

        if response.status == 202:
            if status not in {"running", "awaiting_input"}:
                raise ScanApiError(f"GET report returned HTTP 202 with unexpected status {status!r}")
            return ReportResponse(status=status, report=report)

        # The backend reports a finished scan as "completed"; "done" is kept as
        # an accepted alias for the bundled mock server.
        if status not in {"done", "completed", "failed"}:
            raise ScanApiError(f"GET report returned unexpected status {status!r}")
        return ReportResponse(status=status, report=report)

    def get_report(self, scan_id: str) -> str:
        response = self.get_report_status(scan_id)
        if response.status == "running":
            raise ReportNotReady(f"Report for scan {scan_id} is still running")
        if response.status == "awaiting_input":
            raise ScanApiError(
                f"Scan {scan_id} is paused awaiting user input; this CLI runs "
                "scans non-interactively and cannot resume it"
            )
        if response.status == "failed":
            raise ScanFailed(response.report or f"Scan {scan_id} failed")
        if response.report is None:
            raise ScanApiError("GET report response does not contain report text")
        return response.report

    def wait_for_report(
        self,
        scan_id: str,
        *,
        interval: float = 5.0,
        timeout: float | None = 600.0,
    ) -> str:
        started_at = time.monotonic()

        while True:
            try:
                return self.get_report(scan_id)
            except ReportNotReady:
                if timeout is not None and time.monotonic() - started_at >= timeout:
                    raise TimeoutError(f"Report for scan {scan_id} was not ready in time")
                time.sleep(interval)

    def get_result(self, scan_id: str) -> dict[str, Any]:
        """Fetch the structured CI result ({summary, problems, coverage}).

        Raises ReportNotReady while the scan is still running. A finished
        scan — including a failed one — is returned as-is so the caller can
        gate CI on ``summary.exit_code``.
        """
        escaped_id = quote(scan_id, safe="")
        response = self._request_json(
            "GET",
            f"/scan/{escaped_id}/result",
            headers={"Accept": "application/json"},
            expected_statuses={200, 202},
        )
        if not isinstance(response.data, dict):
            raise ScanApiError("GET result response must be a JSON object")
        if response.status == 202:
            raise ReportNotReady(f"Result for scan {scan_id} is not ready yet")
        return response.data

    def wait_for_result(
        self,
        scan_id: str,
        *,
        interval: float = 5.0,
        timeout: float | None = 600.0,
    ) -> dict[str, Any]:
        started_at = time.monotonic()

        while True:
            try:
                return self.get_result(scan_id)
            except ReportNotReady:
                if timeout is not None and time.monotonic() - started_at >= timeout:
                    raise TimeoutError(f"Result for scan {scan_id} was not ready in time")
                time.sleep(interval)

    def save_report(self, scan_id: str, output: Path, *, wait: bool = False) -> Path:
        output.parent.mkdir(parents=True, exist_ok=True)
        report = self.wait_for_report(scan_id) if wait else self.get_report(scan_id)
        output.write_text(report, encoding="utf-8")
        return output

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        expected_statuses: set[int],
    ) -> "_JsonResponse":
        headers = {"Content-Type": "application/json", **(headers or {})}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            status, response_body = self._request(method, path, body=body, headers=headers)
        except error.HTTPError as exc:
            if exc.code == 404:
                details = _read_http_error_json(exc)
                detail = details.get("detail") if isinstance(details, dict) else None
                raise ScanNotFound(str(detail or "scan not found")) from exc
            if exc.code in (401, 403):
                raise ScanAuthError(
                    f"Scan API rejected the request (HTTP {exc.code}). "
                    "Set a valid key via --api-key or the SCAN_API_KEY environment variable."
                ) from exc
            raise _api_error_from_http(exc) from exc

        if status not in expected_statuses:
            raise ScanApiError(f"Scan API returned unexpected HTTP {status}")

        try:
            data = json.loads(response_body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ScanApiError(f"{method} {path} returned invalid JSON") from exc
        return _JsonResponse(status=status, data=data)

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, bytes]:
        url = f"{self.base_url.rstrip('/')}{path}"
        req = request.Request(url, data=body, headers=headers or {}, method=method)

        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                return response.status, response.read()
        except error.HTTPError:
            raise
        except error.URLError as exc:
            raise ScanApiError(f"Could not reach scan API at {url}: {exc.reason}") from exc


def default_report_path(scan_id: str) -> Path:
    safe_name = _safe_name(scan_id)
    return Path(f"scan-report-{safe_name}.txt")


def default_result_path(scan_id: str) -> Path:
    return Path(f"scan-result-{_safe_name(scan_id)}.json")


def _safe_name(scan_id: str) -> str:
    return "".join(char if char.isalnum() or char in "-_." else "_" for char in scan_id)


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


def _read_http_error_json(exc: error.HTTPError) -> Any:
    try:
        body = exc.read().decode("utf-8", errors="replace")
        return json.loads(body)
    except json.JSONDecodeError:
        return None
    finally:
        exc.close()


@dataclass(frozen=True)
class _JsonResponse:
    status: int
    data: Any
