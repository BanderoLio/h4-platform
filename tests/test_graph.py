"""Тесты графа оркестрации: структура, детерминированные узлы,
интерактивные узлы (clarify, gate) с подменённым ask_user."""
from __future__ import annotations

import unittest

from agentsec import graph as G
from agentsec.config import CONFIG
from agentsec.schema import STATUS_CONFIRMED, STATUS_UNVERIFIED, Coverage, Finding


class _FakeAskUser:
    """Подмена инструмента ask_user: возвращает заранее заданный ответ."""

    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.calls: list[str] = []

    def invoke(self, payload: dict) -> str:
        self.calls.append(payload.get("question", ""))
        return self.answer


class TestGraphStructure(unittest.TestCase):
    def setUp(self) -> None:
        self._stub = CONFIG.stub_specialists
        CONFIG.stub_specialists = True  # не строить реальных ReAct-агентов

    def tearDown(self) -> None:
        CONFIG.stub_specialists = self._stub

    def test_build_graph_has_all_nodes(self):
        compiled = G.build_graph()
        nodes = set(compiled.nodes)
        for expected in (
            "intake", "clarify", "recon", "consolidate",
            "validate", "gate", "report", "patches",
            "specialist_injection", "specialist_secrets", "specialist_authnz",
        ):
            self.assertIn(expected, nodes)


class TestRouting(unittest.TestCase):
    def test_route_after_intake(self):
        self.assertEqual(
            G._route_after_intake({"needs_clarification": True}), "clarify")
        self.assertEqual(
            G._route_after_intake({"needs_clarification": False}), "recon")
        self.assertEqual(G._route_after_intake({}), "recon")


class TestConsolidate(unittest.TestCase):
    def test_consolidate_dedups_and_numbers(self):
        raw = [
            Finding(title="SQLi", cwe="CWE-89", file="app.py:1",
                    severity="High", found_by=["injection"]),
            Finding(title="SQLi", cwe="CWE-89", file="app.py:9",
                    severity="High", found_by=["authnz"]),
        ]
        out = G._consolidate({"raw_findings": raw})
        self.assertEqual(len(out["findings"]), 1)
        self.assertEqual(out["findings"][0].id, "F-001")
        self.assertEqual(sorted(out["findings"][0].found_by),
                         ["authnz", "injection"])


class TestGate(unittest.TestCase):
    def setUp(self) -> None:
        self._interactive = CONFIG.interactive
        self._ask = G.ask_user

    def tearDown(self) -> None:
        CONFIG.interactive = self._interactive
        G.ask_user = self._ask

    def _state(self, status: str) -> dict:
        return {
            "validated_findings": [
                Finding(id="F-001", title="x", severity="Critical", status=status),
            ],
            "coverage": [Coverage(area="injection", status="done")],
        }

    def test_gate_non_interactive_auto_decides(self):
        CONFIG.interactive = False
        out = G._gate(self._state(STATUS_CONFIRMED))
        self.assertEqual(out["verdict"]["verdict"], "FAIL")
        self.assertFalse(out["verdict"]["approved_for_build"])

    def test_gate_interactive_user_approves(self):
        CONFIG.interactive = True
        G.ask_user = _FakeAskUser("да, отдаём")
        out = G._gate(self._state(STATUS_CONFIRMED))
        self.assertTrue(out["verdict"]["approved_for_build"])
        self.assertEqual(out["verdict"]["user_decision"], "да, отдаём")

    def test_gate_interactive_user_rejects(self):
        CONFIG.interactive = True
        G.ask_user = _FakeAskUser("нет")
        out = G._gate(self._state(STATUS_CONFIRMED))
        self.assertFalse(out["verdict"]["approved_for_build"])

    def test_gate_coverage_gap_downgrades_pass(self):
        CONFIG.interactive = False
        state = {
            "validated_findings": [],
            "coverage": [Coverage(area="authnz", status="gap", note="timeout")],
        }
        out = G._gate(state)
        # Чистый PASS без находок, но пробел покрытия -> NEEDS_REVIEW.
        self.assertEqual(out["verdict"]["verdict"], "NEEDS_REVIEW")


class TestClarify(unittest.TestCase):
    def setUp(self) -> None:
        self._ask = G.ask_user

    def tearDown(self) -> None:
        G.ask_user = self._ask

    def test_clarify_records_qa(self):
        G.ask_user = _FakeAskUser("смотри каталог src/")
        out = G._clarify({"clarifying_question": "Какой скоуп?"})
        self.assertEqual(len(out["clarifications"]), 1)
        self.assertEqual(out["clarifications"][0]["answer"], "смотри каталог src/")


class TestSpecialistNode(unittest.TestCase):
    def setUp(self) -> None:
        self._stub = CONFIG.stub_specialists
        CONFIG.stub_specialists = False

    def tearDown(self) -> None:
        CONFIG.stub_specialists = self._stub

    def test_timeout_marks_coverage_gap_without_retry(self):
        calls = []

        def _slow_runner(_task: str) -> str:
            calls.append(1)
            raise TimeoutError("специалист не уложился в лимит")

        node = G._make_specialist_node("injection", _slow_runner)
        out = node({"task": "t", "recon": "", "scope": {}})
        # Таймаут -> пробел покрытия, и ровно одна попытка (без ретрая).
        self.assertEqual(len(calls), 1)
        self.assertEqual(out["coverage"][0].status, "gap")
        self.assertEqual(out["coverage"][0].area, "injection")

    def test_empty_report_is_retried(self):
        calls = []

        def _empty_runner(_task: str) -> str:
            calls.append(1)
            return ""

        node = G._make_specialist_node("secrets", _empty_runner)
        out = node({"task": "t", "recon": "", "scope": {}})
        # Пустой отчёт -> ретраи (specialist_retries + 1 попытка).
        self.assertEqual(len(calls), CONFIG.specialist_retries + 1)
        self.assertEqual(out["coverage"][0].status, "gap")


class TestReport(unittest.TestCase):
    def test_report_renders_markdown(self):
        state = {
            "validated_findings": [
                Finding(id="F-001", title="x", severity="High",
                        status=STATUS_CONFIRMED),
            ],
            "verdict": {"verdict": "FAIL", "severity_counts": {"High": 1}},
            "coverage": [Coverage(area="injection", status="done")],
            "task": "audit",
            "repo": "/x",
        }
        out = G._report(state)
        self.assertIn("# Отчёт анализа безопасности", out["report_md"])
        self.assertIn("F-001", out["report_md"])


class TestPatches(unittest.TestCase):
    def setUp(self) -> None:
        self._enabled = CONFIG.generate_fix_patches
        self._gen = G.generate_fix_patches

    def tearDown(self) -> None:
        CONFIG.generate_fix_patches = self._enabled
        G.generate_fix_patches = self._gen

    def test_patches_disabled_returns_empty(self):
        CONFIG.generate_fix_patches = False
        out = G._patches({"validated_findings": []})
        self.assertEqual(out["fix_patches"], [])

    def test_patches_node_uses_generator_output(self):
        CONFIG.generate_fix_patches = True
        G.generate_fix_patches = lambda **_: [{
            "finding_id": "F-001",
            "title": "SQLi",
            "unified_diff": "--- a/app.py\n+++ b/app.py\n@@\n-x\n+y\n",
        }]
        out = G._patches({
            "validated_findings": [
                Finding(id="F-001", title="SQLi", severity="High",
                        status=STATUS_CONFIRMED),
            ],
            "repo": "/tmp/x",
        })
        self.assertEqual(len(out["fix_patches"]), 1)
        self.assertIn("unified_diff", out["fix_patches"][0])


if __name__ == "__main__":
    unittest.main()
