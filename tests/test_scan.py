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


if __name__ == "__main__":
    unittest.main()
