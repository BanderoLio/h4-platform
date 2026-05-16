from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from .client import (
    DEFAULT_BASE_URL,
    ReportNotReady,
    ScanApiError,
    ScanClient,
    ScanFailed,
    ScanNotFound,
    default_report_path,
    default_result_path,
)
from .interactive import InteractiveApp


def build_parser() -> argparse.ArgumentParser:
    connection_options = argparse.ArgumentParser(add_help=False)
    _add_connection_options(connection_options, suppress_defaults=True)

    parser = argparse.ArgumentParser(
        prog="agent-scan",
        description="Start repository scans and download TXT reports.",
    )
    _add_connection_options(parser)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command")

    start = subparsers.add_parser(
        "start",
        help="Start a repository scan.",
        parents=[connection_options],
    )
    start.add_argument(
        "repo_url",
        help="Repository to scan: an http(s) URL (cloned by the backend) "
        "or a server-side local path (needs ALLOWED_LOCAL_ROOTS).",
    )
    start.add_argument("--webhook-url", help="Optional URL to receive the report when the scan completes.")

    report = subparsers.add_parser(
        "report",
        help="Download a finished scan report.",
        parents=[connection_options],
    )
    report.add_argument("scan_id", help="Scan id returned by the start command.")
    report.add_argument("-o", "--output", type=Path, help="Where to write the TXT report.")

    scan = subparsers.add_parser(
        "scan",
        help="Start a scan and wait until the TXT report is ready.",
        parents=[connection_options],
    )
    scan.add_argument(
        "repo_url",
        help="Repository to scan: an http(s) URL (cloned by the backend) "
        "or a server-side local path (needs ALLOWED_LOCAL_ROOTS).",
    )
    scan.add_argument("--webhook-url", help="Optional URL to receive the report when the scan completes.")
    scan.add_argument("-o", "--output", type=Path, help="Where to write the TXT report.")
    scan.add_argument("--interval", type=float, default=5.0, help="Polling interval in seconds.")
    scan.add_argument(
        "--wait-timeout",
        type=float,
        default=600.0,
        help="Maximum time to wait for the report in seconds. Use 0 to wait forever.",
    )

    result = subparsers.add_parser(
        "result",
        help="Fetch the structured JSON result of a scan and exit with its quality-gate code.",
        parents=[connection_options],
    )
    result.add_argument("scan_id", help="Scan id returned by the start command.")
    result.add_argument("-o", "--output", type=Path, help="Where to write the JSON result.")
    result.add_argument("--interval", type=float, default=5.0, help="Polling interval in seconds.")
    result.add_argument(
        "--wait-timeout",
        type=float,
        default=600.0,
        help="Maximum time to wait for the result in seconds. Use 0 to wait forever.",
    )
    result.add_argument(
        "--no-wait",
        action="store_true",
        help="Do not poll: fail with code 4 if the scan is not finished yet.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    argv = sys.argv[1:] if argv is None else argv

    if not argv:
        if sys.stdin.isatty():
            return run_interactive()
        parser.print_help()
        return 0

    args = parser.parse_args(argv)
    if args.command is None:
        if sys.stdin.isatty():
            return run_interactive(
                initial_base_url=args.base_url,
                initial_timeout=args.timeout,
                initial_api_key=args.api_key,
            )
        parser.print_help()
        return 0

    return _run_command(args)


def run_interactive(
    *,
    initial_base_url: str | None = None,
    initial_timeout: float = 30.0,
    initial_api_key: str | None = None,
) -> int:
    return InteractiveApp(
        initial_base_url=initial_base_url,
        initial_timeout=initial_timeout,
        initial_api_key=initial_api_key,
    ).run()


def _run_command(args: argparse.Namespace) -> int:
    client = ScanClient(base_url=args.base_url, timeout=args.timeout, api_key=args.api_key)

    try:
        if args.command == "start":
            scan_id = client.start_scan(args.repo_url, webhook_url=args.webhook_url)
            print(scan_id)
            return 0

        if args.command == "report":
            output = args.output or default_report_path(args.scan_id)
            client.save_report(args.scan_id, output)
            print(f"Report saved: {output}")
            return 0

        if args.command == "scan":
            scan_id = client.start_scan(args.repo_url, webhook_url=args.webhook_url)
            print(f"Scan started: {scan_id}", file=sys.stderr)

            wait_timeout = None if args.wait_timeout == 0 else args.wait_timeout
            report = client.wait_for_report(
                scan_id,
                interval=args.interval,
                timeout=wait_timeout,
            )

            output = args.output or default_report_path(scan_id)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(report, encoding="utf-8")
            print(f"Report saved: {output}")
            return 0

        if args.command == "result":
            return _run_result(client, args)

        raise AssertionError(f"Unknown command: {args.command}")
    except ReportNotReady:
        print("Report is still running.", file=sys.stderr)
        return 4
    except ScanNotFound as exc:
        print(f"Scan not found: {exc}", file=sys.stderr)
        return 5
    except ScanFailed as exc:
        print(f"Scan failed: {exc}", file=sys.stderr)
        return 6
    except TimeoutError as exc:
        print(f"Timed out: {exc}", file=sys.stderr)
        return 3
    except ScanApiError as exc:
        print(f"API error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130


def _run_result(client: ScanClient, args: argparse.Namespace) -> int:
    """Fetch the structured result and return the quality-gate exit code.

    The return value is the orchestrator's CI code (0 = pass, 1 = fail,
    2 = needs review), so `agent-scan result` can gate a pipeline directly.
    """
    if args.no_wait:
        data = client.get_result(args.scan_id)
    else:
        wait_timeout = None if args.wait_timeout == 0 else args.wait_timeout
        data = client.wait_for_result(
            args.scan_id, interval=args.interval, timeout=wait_timeout
        )

    output = args.output or default_result_path(args.scan_id)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary = data.get("summary", {}) if isinstance(data, dict) else {}
    counts = summary.get("severity_counts") or {}
    counts_str = ", ".join(f"{k}: {v}" for k, v in counts.items()) or "—"
    print(f"Result saved: {output}", file=sys.stderr)
    print(
        f"Quality gate: {summary.get('verdict', 'N/A')} | "
        f"problems: {summary.get('total_problems', 0)} ({counts_str})",
        file=sys.stderr,
    )
    exit_code = summary.get("exit_code")
    return exit_code if isinstance(exit_code, int) else 1


def _add_connection_options(parser: argparse.ArgumentParser, *, suppress_defaults: bool = False) -> None:
    default = argparse.SUPPRESS if suppress_defaults else os.getenv("SCAN_API_URL", DEFAULT_BASE_URL)
    timeout_default = argparse.SUPPRESS if suppress_defaults else 30.0
    api_key_default = argparse.SUPPRESS if suppress_defaults else os.getenv("SCAN_API_KEY")
    parser.add_argument(
        "--base-url",
        default=default,
        help=f"Scan API base URL. Defaults to SCAN_API_URL or {DEFAULT_BASE_URL}.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=timeout_default,
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--api-key",
        default=api_key_default,
        help="Bearer key for the scan API. Defaults to the SCAN_API_KEY environment variable.",
    )


if __name__ == "__main__":
    raise SystemExit(main())
