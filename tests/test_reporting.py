"""Тесты рендера и сохранения отчётов."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agentsec.reporting import (
    build_structured_result,
    findings_to_jsonable,
    render_report,
    save_report,
)
from agentsec.schema import STATUS_CONFIRMED, Coverage, Finding, compute_verdict


def _sample_findings() -> list[Finding]:
    return [
        Finding(id="F-001", title="SQLi", severity="Critical",
                status=STATUS_CONFIRMED, cwe="CWE-89", file="app.py:42",
                cvss=9.8, found_by=["injection"]),
        Finding(id="F-002", title="IDOR", severity="High",
                status=STATUS_CONFIRMED, file="app.py:33", found_by=["authnz"]),
    ]


class TestRender(unittest.TestCase):
    def test_render_report_structure(self):
        findings = _sample_findings()
        verdict = compute_verdict(findings)
        report = render_report(
            findings=findings, verdict=verdict,
            coverage=[Coverage(area="injection", status="done")],
            task="audit", repo="/x",
        )
        self.assertIn("# Отчёт анализа безопасности", report)
        self.assertIn("## Quality gate", report)
        self.assertIn("FAIL", report)
        self.assertIn("F-001", report)
        self.assertIn("## Покрытие", report)

    def test_render_empty_findings(self):
        report = render_report(findings=[], verdict={}, coverage=[])
        self.assertIn("Уязвимости не подтверждены", report)


class TestJsonable(unittest.TestCase):
    def test_findings_to_jsonable_from_dataclass(self):
        rows = findings_to_jsonable(_sample_findings())
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["id"], "F-001")
        self.assertEqual(rows[0]["cvss"], 9.8)

    def test_findings_to_jsonable_from_markdown(self):
        rows = findings_to_jsonable(markdown="### [High] X\n- **CWE:** CWE-1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "X")


class TestSaveReport(unittest.TestCase):
    def test_writes_md_and_json_with_verdict(self):
        findings = _sample_findings()
        verdict = compute_verdict(findings)
        coverage = [Coverage(area="injection", status="done")]
        with tempfile.TemporaryDirectory() as tmp:
            paths = save_report(
                markdown=render_report(findings=findings, verdict=verdict,
                                       coverage=coverage),
                findings=findings, output_dir=tmp, formats=["md", "json"],
                task="audit", repo="repo", verdict=verdict, coverage=coverage,
            )
            self.assertTrue(paths["markdown"].exists())
            self.assertTrue(paths["json"].exists())
            payload = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
            self.assertEqual(payload["verdict"]["verdict"], "FAIL")
            self.assertEqual(len(payload["findings"]), 2)
            self.assertEqual(len(payload["coverage"]), 1)


class TestStructuredResult(unittest.TestCase):
    def test_summary_and_problems_from_findings(self):
        findings = _sample_findings()
        verdict = compute_verdict(findings)
        result = build_structured_result(
            findings=findings, verdict=verdict,
            coverage=[Coverage(area="injection", status="done")],
            status="completed", scan_id="abc", task="audit", repo="/x",
        )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["summary"]["verdict"], "FAIL")
        self.assertEqual(result["summary"]["exit_code"], 1)
        self.assertEqual(len(result["problems"]), 2)
        self.assertEqual(result["problems"][0]["id"], "F-001")
        # file:line is split into separate fields for CI annotations.
        self.assertEqual(result["problems"][0]["file"], "app.py")
        self.assertEqual(result["problems"][0]["line"], 42)
        self.assertEqual(len(result["coverage"]), 1)

    def test_file_field_tolerates_backticks_and_line_ranges(self):
        finding = Finding(id="F-009", title="X", severity="High",
                          file="`app.py:33-51`")
        result = build_structured_result(findings=[finding], verdict={})
        self.assertEqual(result["problems"][0]["file"], "app.py")
        self.assertEqual(result["problems"][0]["line"], 33)

    def test_failed_scan_is_a_blocking_result(self):
        result = build_structured_result(
            findings=[], verdict={}, status="failed", error="boom",
        )
        self.assertEqual(result["summary"]["verdict"], "FAIL")
        self.assertEqual(result["summary"]["exit_code"], 1)
        self.assertEqual(result["error"], "boom")


if __name__ == "__main__":
    unittest.main()
