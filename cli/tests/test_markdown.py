from __future__ import annotations

import unittest

from agent_scan_cli.markdown import render_markdown


class MarkdownRenderTests(unittest.TestCase):
    def test_plain_mode_strips_markup(self) -> None:
        rendered = render_markdown(
            "# Title\n\n- **Severity:** High\n- plain item\n\n`code`",
            color=False,
        )
        # No ANSI escapes and no leftover ** markers when colour is off.
        self.assertNotIn("\033[", rendered)
        self.assertNotIn("**", rendered)
        self.assertIn("Title", rendered)
        self.assertIn("Severity: High", rendered)
        self.assertIn("•", rendered)

    def test_color_mode_emits_ansi(self) -> None:
        rendered = render_markdown("## Heading\n\n**bold**", color=True)
        self.assertIn("\033[", rendered)
        self.assertIn("Heading", rendered)

    def test_fenced_code_block_is_kept_verbatim(self) -> None:
        rendered = render_markdown("```\nrm -rf /\n```", color=False)
        self.assertIn("rm -rf /", rendered)
        self.assertNotIn("```", rendered)


if __name__ == "__main__":
    unittest.main()
