from __future__ import annotations

import argparse
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
    start.add_argument("repo_url", help="Repository URL to scan.")
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
    scan.add_argument("repo_url", help="Repository URL to scan.")
    scan.add_argument("--webhook-url", help="Optional URL to receive the report when the scan completes.")
    scan.add_argument("-o", "--output", type=Path, help="Where to write the TXT report.")
    scan.add_argument("--interval", type=float, default=5.0, help="Polling interval in seconds.")
    scan.add_argument(
        "--wait-timeout",
        type=float,
        default=600.0,
        help="Maximum time to wait for the report in seconds. Use 0 to wait forever.",
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
            return run_interactive(initial_base_url=args.base_url, initial_timeout=args.timeout)
        parser.print_help()
        return 0

    return _run_command(args)


def run_interactive(
    *,
    initial_base_url: str | None = None,
    initial_timeout: float = 30.0,
) -> int:
    return InteractiveApp(
        initial_base_url=initial_base_url,
        initial_timeout=initial_timeout,
    ).run()


def _run_command(args: argparse.Namespace) -> int:
    client = ScanClient(base_url=args.base_url, timeout=args.timeout)

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


def _add_connection_options(parser: argparse.ArgumentParser, *, suppress_defaults: bool = False) -> None:
    default = argparse.SUPPRESS if suppress_defaults else os.getenv("SCAN_API_URL", DEFAULT_BASE_URL)
    timeout_default = argparse.SUPPRESS if suppress_defaults else 30.0
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


if __name__ == "__main__":
    raise SystemExit(main())
