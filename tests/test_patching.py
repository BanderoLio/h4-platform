"""Тесты утилит генерации candidate-патчей (без вызова LLM)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentsec.patching import _read_context


class TestReadContext(unittest.TestCase):
    def test_parses_markdown_file_ref_with_range(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "backend/game_logic/routes.py"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                "line1\nline2\nline3\nline4\nline5\nline6\n", encoding="utf-8"
            )
            rel, snippet, err = _read_context(
                root,
                "`backend/game_logic/routes.py:5‑6`",
            )
            self.assertIsNone(err)
            self.assertEqual(rel, "backend/game_logic/routes.py")
            self.assertIn("5: line5", snippet)

    def test_tries_next_candidate_when_first_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "backend/firemap/routes.py"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("a\nb\nc\n", encoding="utf-8")
            rel, snippet, err = _read_context(
                root,
                "`missing/routes.py:1` и `backend/firemap/routes.py:2`",
            )
            self.assertIsNone(err)
            self.assertEqual(rel, "backend/firemap/routes.py")
            self.assertIn("2: b", snippet)


if __name__ == "__main__":
    unittest.main()
