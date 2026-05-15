from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from agent_scan_cli.cli import build_parser, main, run_interactive
from agent_scan_cli.client import ReportNotReady, ScanFailed, ScanNotFound
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
        interactive.assert_called_once_with(initial_base_url="http://api.test", initial_timeout=9)


if __name__ == "__main__":
    unittest.main()
