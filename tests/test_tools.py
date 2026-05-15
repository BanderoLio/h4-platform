"""Тесты инструментов: сканеры корректно деградируют без установленных бинарей."""
from __future__ import annotations

import json
import shutil
import unittest

from agentsec.tools.scanners import run_selected_scanners, run_semgrep


class TestScanners(unittest.TestCase):
    def test_missing_binary_reports_unavailable_not_crash(self):
        # semgrep может быть не установлен — инструмент обязан вернуть
        # явный статус, а не упасть.
        out = run_semgrep.invoke({"config": "auto"})
        parsed = json.loads(out)
        self.assertIn("status", parsed)
        if shutil.which("semgrep") is None:
            self.assertEqual(parsed["status"], "unavailable")

    def test_run_selected_scanners_returns_dict(self):
        outputs = run_selected_scanners(["semgrep"])
        self.assertIn("semgrep", outputs)
        # Каждый вывод — валидный JSON со статусом.
        self.assertIn("status", json.loads(outputs["semgrep"]))


if __name__ == "__main__":
    unittest.main()
