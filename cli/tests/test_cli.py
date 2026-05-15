from __future__ import annotations

import unittest
from unittest.mock import patch

from cli.src.agent_scan_cli.cli import build_parser, main, run_interactive
from cli.src.agent_scan_cli.client import ReportNotReady


class CliTests(unittest.TestCase):
    def test_connection_options_work_after_subcommand(self) -> None:
        args = build_parser().parse_args(
            ["start", "https://github.com/org/repo", "--base-url", "http://api.test", "--timeout", "7"]
        )

        self.assertEqual(args.base_url, "http://api.test")
        self.assertEqual(args.timeout, 7)

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

    def test_no_subcommand_is_valid_for_interactive_mode(self) -> None:
        args = build_parser().parse_args([])

        self.assertIsNone(args.command)

    def test_interactive_menu_can_exit(self) -> None:
        lines: list[str] = []

        exit_code = run_interactive(input_func=lambda _prompt: "5", output=lambda *args, **_kwargs: lines.append(str(args[0])))

        self.assertEqual(exit_code, 0)
        self.assertTrue(any("AGENT SCAN CONSOLE" in line for line in lines))

    def test_global_options_without_subcommand_open_interactive_mode(self) -> None:
        with patch("agent_scan_cli.cli.sys.stdin.isatty", return_value=True):
            with patch("agent_scan_cli.cli.run_interactive", return_value=0) as interactive:
                exit_code = main(["--base-url", "http://api.test", "--timeout", "9"])

        self.assertEqual(exit_code, 0)
        interactive.assert_called_once_with(initial_base_url="http://api.test", initial_timeout=9)


if __name__ == "__main__":
    unittest.main()
