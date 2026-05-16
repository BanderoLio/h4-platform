"""Тесты интеграции сканеров: классификация правил, разбор JSON валидатора."""
from __future__ import annotations

import unittest

from agentsec.agents.validator import _extract_json
from agentsec.index.scan import classify_rule


class ClassifyRuleTest(unittest.TestCase):
    def test_rule_to_vuln_class(self):
        self.assertEqual(
            classify_rule("python.lang.security.audit.sql-injection"),
            "injection")
        self.assertEqual(
            classify_rule("generic.secrets.hardcoded-token"), "secrets")
        self.assertEqual(
            classify_rule("go.lang.security.missing-authz-check"), "authnz")
        self.assertEqual(classify_rule("python.weak-md5"), "secrets")
        # Неизвестное правило → дефолт injection.
        self.assertEqual(classify_rule("some.unknown.rule"), "injection")


class ValidatorJsonTest(unittest.TestCase):
    """Прогон Grafana показал: валидатор не парсил JSON в обёртках."""

    def test_plain_object(self):
        self.assertEqual(_extract_json('{"status": "confirmed"}')["status"],
                         "confirmed")

    def test_markdown_fence(self):
        out = _extract_json('```json\n{"status": "likely"}\n```')
        self.assertEqual(out["status"], "likely")

    def test_single_quotes(self):
        self.assertEqual(_extract_json("{'status': 'false_positive'}")["status"],
                         "false_positive")

    def test_trailing_comma(self):
        out = _extract_json('{"status": "confirmed", "cvss": 9.8,}')
        self.assertEqual(out["cvss"], 9.8)

    def test_prose_around_json(self):
        out = _extract_json('Вот вердикт: {"status": "confirmed"} — готово.')
        self.assertEqual(out["status"], "confirmed")

    def test_no_json_raises(self):
        with self.assertRaises(ValueError):
            _extract_json("никакого джейсона тут нет")


class ScannerFindingsNodeTest(unittest.TestCase):
    """semgrep-находки из индекса → прямые Finding-и (узел графа)."""

    def setUp(self) -> None:
        import tempfile
        from pathlib import Path

        from agentsec.config import CONFIG
        from agentsec.index import index_repo
        from agentsec.index.store import IndexStore, index_db_path

        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        (root / "app.py").write_text("def f(): pass\n", encoding="utf-8")
        index_repo(root)[0].close()
        store = IndexStore(index_db_path(root))
        store.replace_scanner_findings([
            {"tool": "semgrep", "rule": "py.security.sqli",
             "vuln_class": "injection", "file": "app.py", "line": 1,
             "severity": "ERROR", "message": "tainted SQL"},
            {"tool": "semgrep", "rule": "py.audit.weak-hash",
             "vuln_class": "secrets", "file": "app.py", "line": 1,
             "severity": "WARNING", "message": "md5"},
        ])
        store.close()
        self._saved_root = CONFIG.analysis_root
        CONFIG.analysis_root = root

    def tearDown(self) -> None:
        from agentsec.config import CONFIG
        CONFIG.analysis_root = self._saved_root
        self._tmp.cleanup()

    def test_semgrep_findings_become_direct_findings(self):
        from agentsec.graph import _scanner_findings_node
        out = _scanner_findings_node({})
        findings = out["raw_findings"]
        self.assertEqual(len(findings), 2)
        sev = {f.severity for f in findings}
        self.assertEqual(sev, {"High", "Medium"})        # ERROR→High, WARNING→Medium
        self.assertTrue(all(f.found_by == ["semgrep"] for f in findings))


if __name__ == "__main__":
    unittest.main()
