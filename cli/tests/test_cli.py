from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from agent_scan_cli.cli import build_parser, main, run_interactive
from agent_scan_cli.client import (
    ReportNotReady,
    ScanAuthError,
    ScanFailed,
    ScanNotFound,
)
from agent_scan_cli.interactive import InteractiveApp
from agent_scan_cli.terminal import Terminal


class CliTests(unittest.TestCase):
    def test_connection_options_work_after_subcommand(self) -> None:
        args = build_parser().parse_args(
            [
                "start",
                "https://github.com/org/repo",
                "--webhook-url",
                "https://hooks.test/report",
                "--base-url",
                "http://api.test",
                "--timeout",
                "7",
            ]
        )

        self.assertEqual(args.base_url, "http://api.test")
        self.assertEqual(args.timeout, 7)
        self.assertEqual(args.webhook_url, "https://hooks.test/report")

    def test_connection_options_work_before_subcommand(self) -> None:
        args = build_parser().parse_args(
            ["--base-url", "http://api.test", "--timeout", "7", "start", "https://github.com/org/repo"]
        )

        self.assertEqual(args.base_url, "http://api.test")
        self.assertEqual(args.timeout, 7)

    def test_report_not_ready_exits_with_dedicated_code(self) -> None:
        with patch("agent_scan_cli.cli.ScanClient.get_report", side_effect=ReportNotReady("pending")):
            exit_code = main(["report", "scan-123"])

        self.assertEqual(exit_code, 4)

    def test_scan_not_found_exits_with_dedicated_code(self) -> None:
        with patch("agent_scan_cli.cli.ScanClient.get_report", side_effect=ScanNotFound("scan not found")):
            exit_code = main(["report", "scan-123"])

        self.assertEqual(exit_code, 5)

    def test_scan_failed_exits_with_dedicated_code(self) -> None:
        with patch("agent_scan_cli.cli.ScanClient.get_report", side_effect=ScanFailed("clone failed")):
            exit_code = main(["report", "scan-123"])

        self.assertEqual(exit_code, 6)

    def test_scan_command_writes_text_report(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "report.txt"
            with patch("agent_scan_cli.cli.ScanClient.start_scan", return_value="scan-123"):
                with patch("agent_scan_cli.cli.ScanClient.wait_for_report", return_value="plain text report"):
                    exit_code = main(["scan", "https://github.com/org/repo", "--output", str(output)])

            self.assertEqual(exit_code, 0)
            self.assertEqual(output.read_text(), "plain text report")

    def test_result_command_writes_json_and_exits_with_quality_gate_code(self) -> None:
        result_payload = {
            "scan_id": "scan-9",
            "status": "completed",
            "summary": {"verdict": "FAIL", "exit_code": 1, "total_problems": 2,
                        "severity_counts": {"High": 2}},
            "problems": [{"id": "F-001"}, {"id": "F-002"}],
        }
        with TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "result.json"
            with patch("agent_scan_cli.cli.ScanClient.wait_for_result", return_value=result_payload):
                exit_code = main(["result", "scan-9", "--output", str(output)])

            self.assertEqual(exit_code, 1)
            self.assertEqual(json.loads(output.read_text())["summary"]["verdict"], "FAIL")

    def test_result_command_exits_zero_on_pass(self) -> None:
        result_payload = {"status": "completed", "summary": {"verdict": "PASS", "exit_code": 0},
                          "problems": []}
        with TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "result.json"
            with patch("agent_scan_cli.cli.ScanClient.wait_for_result", return_value=result_payload):
                exit_code = main(["result", "scan-9", "--output", str(output)])

            self.assertEqual(exit_code, 0)

    def test_result_command_no_wait_reports_not_ready(self) -> None:
        with patch("agent_scan_cli.cli.ScanClient.get_result", side_effect=ReportNotReady("pending")):
            exit_code = main(["result", "scan-9", "--no-wait"])

        self.assertEqual(exit_code, 4)

    def test_no_subcommand_is_valid_for_interactive_mode(self) -> None:
        args = build_parser().parse_args([])

        self.assertIsNone(args.command)

    def test_interactive_menu_can_exit(self) -> None:
        lines: list[str] = []
        terminal = Terminal(
            input_func=lambda _prompt: "5",
            output=lambda *args, **_kwargs: lines.append(str(args[0])),
            color=False,
        )

        exit_code = InteractiveApp(terminal=terminal).run()

        self.assertEqual(exit_code, 0)
        self.assertTrue(any("█████" in line for line in lines))

    def test_global_options_without_subcommand_open_interactive_mode(self) -> None:
        with patch("agent_scan_cli.cli.sys.stdin.isatty", return_value=True):
            with patch("agent_scan_cli.cli.run_interactive", return_value=0) as interactive:
                exit_code = main(["--base-url", "http://api.test", "--timeout", "9"])

        self.assertEqual(exit_code, 0)
        interactive.assert_called_once_with(
            initial_base_url="http://api.test", initial_timeout=9, initial_api_key=None
        )


class InteractiveAuthRetryTests(unittest.TestCase):
    """The interactive mode must recover from a missing/invalid API key by
    prompting for one and retrying, instead of failing the whole action."""

    @staticmethod
    def _app(inputs: list[str]) -> InteractiveApp:
        feed = iter(inputs)
        terminal = Terminal(
            input_func=lambda _prompt: next(feed, ""),
            output=lambda *args, **_kwargs: None,
            color=False,
        )
        app = InteractiveApp(terminal=terminal)
        # Start with no key regardless of the test runner's environment.
        app.state.api_key = None
        return app

    def test_auth_retry_prompts_for_key_and_retries(self) -> None:
        app = self._app(["entered-key"])
        seen_keys: list[str | None] = []

        def action() -> str:
            seen_keys.append(app.state.api_key)
            if app.state.api_key is None:
                raise ScanAuthError("Scan API rejected the request (HTTP 403).")
            return "done"

        result = app._call_with_auth_retry(action)

        self.assertEqual(result, "done")
        self.assertEqual(app.state.api_key, "entered-key")
        self.assertEqual(seen_keys, [None, "entered-key"])

    def test_auth_retry_reraises_when_key_prompt_cancelled(self) -> None:
        # Empty input == cancel: the auth error propagates unchanged.
        app = self._app([""])

        def action() -> str:
            raise ScanAuthError("Scan API rejected the request (HTTP 403).")

        with self.assertRaises(ScanAuthError):
            app._call_with_auth_retry(action)


if __name__ == "__main__":
    unittest.main()
