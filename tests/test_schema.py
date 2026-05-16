"""Тесты схемы находок: парсинг, дедупликация, quality gate."""
from __future__ import annotations

import unittest

from agentsec.schema import (
    STATUS_CONFIRMED,
    STATUS_FALSE_POSITIVE,
    STATUS_UNVERIFIED,
    VERDICT_FAIL,
    VERDICT_PASS,
    VERDICT_REVIEW,
    Finding,
    compute_verdict,
    deduplicate,
    parse_findings_markdown,
    severity_key,
)

_MD = """\
### [High] SQL injection in login
- **CWE:** CWE-89
- **Severity:** High
- **Confidence:** Likely
- **Файл:** app.py:42
- **Описание:** untrusted input reaches the query
- **Поток данных:** request -> cursor.execute
- **PoC:** ' OR 1=1
- **Рекомендация:** use parameterized queries

### [Critical] Command injection in /ping
- **CWE:** CWE-78
- **Severity:** Critical
- **Файл:** app.py:99
"""


class TestParsing(unittest.TestCase):
    def test_parses_each_block(self):
        findings = parse_findings_markdown(_MD, vuln_class="injection",
                                           found_by=["injection"])
        self.assertEqual(len(findings), 2)
        self.assertEqual(findings[0].title, "SQL injection in login")
        self.assertEqual(findings[0].cwe, "CWE-89")
        self.assertEqual(findings[0].file, "app.py:42")
        self.assertEqual(findings[0].vuln_class, "injection")
        self.assertEqual(findings[0].found_by, ["injection"])

    def test_empty_and_no_findings(self):
        self.assertEqual(parse_findings_markdown(""), [])
        self.assertEqual(parse_findings_markdown("Уязвимостей не найдено."), [])


class TestDeduplicate(unittest.TestCase):
    def test_merges_same_fingerprint(self):
        a = parse_findings_markdown(_MD, vuln_class="injection",
                                    found_by=["injection"])
        b = parse_findings_markdown(_MD, vuln_class="authnz",
                                    found_by=["authnz"])
        merged = deduplicate(a + b)
        self.assertEqual(len(merged), 2)  # 4 находки -> 2 уникальных
        for finding in merged:
            self.assertEqual(sorted(finding.found_by), ["authnz", "injection"])

    def test_assigns_ids_and_sorts_by_severity(self):
        merged = deduplicate(parse_findings_markdown(_MD))
        self.assertEqual([f.id for f in merged], ["F-001", "F-002"])
        self.assertEqual(merged[0].severity, "Critical")  # выше — первым

    def test_fingerprint_ignores_line_number(self):
        f1 = Finding(title="x", cwe="CWE-89", file="app.py:42")
        f2 = Finding(title="x", cwe="CWE-89", file="app.py:777")
        self.assertEqual(f1.fingerprint(), f2.fingerprint())


class TestVerdict(unittest.TestCase):
    def test_empty_is_pass(self):
        self.assertEqual(compute_verdict([])["verdict"], VERDICT_PASS)

    def test_confirmed_high_is_fail(self):
        f = Finding(title="x", severity="High", status=STATUS_CONFIRMED)
        result = compute_verdict([f])
        self.assertEqual(result["verdict"], VERDICT_FAIL)
        self.assertEqual(result["blocking"], [f.id])

    def test_unverified_high_is_review(self):
        f = Finding(title="x", severity="Critical", status=STATUS_UNVERIFIED)
        self.assertEqual(compute_verdict([f])["verdict"], VERDICT_REVIEW)

    def test_low_severity_is_pass(self):
        f = Finding(title="x", severity="Low", status=STATUS_CONFIRMED)
        self.assertEqual(compute_verdict([f])["verdict"], VERDICT_PASS)

    def test_false_positive_not_counted(self):
        f = Finding(title="x", severity="Critical", status=STATUS_FALSE_POSITIVE)
        self.assertEqual(compute_verdict([f])["verdict"], VERDICT_PASS)


class TestSeverityKey(unittest.TestCase):
    def test_edge_cases(self):
        self.assertEqual(severity_key(""), "Info")
        self.assertEqual(severity_key("   "), "Info")
        self.assertEqual(severity_key("critical"), "Critical")
        self.assertEqual(severity_key("High (CWE-89)"), "High")


if __name__ == "__main__":
    unittest.main()
