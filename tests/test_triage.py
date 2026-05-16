"""Тесты триаж-воркера: сбор кандидатов, батчи, бюджет, инкрементальность."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentsec.config import CONFIG
from agentsec.index import index_repo

_APP = """\
import sqlite3

def q1(x):
    return db.execute("select " + x)

def q2(x):
    return db.execute("select " + x)

def q3(x):
    return db.execute("select " + x)

def q4(x):
    return db.execute("select " + x)

@app.route("/p")
def p(x):
    return db.execute("select " + x)
"""


class _Reply:
    def __init__(self, content: str) -> None:
        self.content = content


class _StubLLM:
    """LLM-стаб: на каждый вызов — JSON-массив с одной находкой.

    `fail_on_call` — номер вызова (1-based), на котором кинуть исключение
    (для проверки сохранения частичного результата)."""

    def __init__(self, fail_on_call: int = 0) -> None:
        self.calls = 0
        self.fail_on_call = fail_on_call

    def invoke(self, _messages):
        self.calls += 1
        if self.calls == self.fail_on_call:
            raise RuntimeError("batch boom")
        return _Reply('[{"index": 1, "title": "SQLi", "severity": "High", '
                      '"cwe": "CWE-89", "confidence": "Likely", '
                      '"description": "d", "data_flow": "s->k", '
                      '"poc": "p", "recommendation": "r"}]')


class TriageTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        (root / "app.py").write_text(_APP, encoding="utf-8")
        index_repo(root)[0].close()

        self._saved = (CONFIG.analysis_root, CONFIG.triage_batch_size,
                       CONFIG.triage_budget_sec,
                       CONFIG.max_candidates_per_specialist)
        CONFIG.analysis_root = root
        CONFIG.triage_batch_size = 3
        CONFIG.triage_budget_sec = 600
        CONFIG.max_candidates_per_specialist = 60

        import agentsec.agents.triage as triage_mod
        self.triage = triage_mod
        self._saved_llm = triage_mod.build_llm

    def tearDown(self) -> None:
        (CONFIG.analysis_root, CONFIG.triage_batch_size,
         CONFIG.triage_budget_sec,
         CONFIG.max_candidates_per_specialist) = self._saved
        self.triage.build_llm = self._saved_llm
        self._tmp.cleanup()

    def test_gather_returns_candidates_with_code(self):
        cands = self.triage._gather("injection")
        self.assertGreaterEqual(len(cands), 5)          # 5 sql sink-ов + точка входа
        self.assertTrue(all("code" in c and c["code"] for c in cands))
        self.assertTrue(any(c["kind"] == "sink:sql" for c in cands))
        self.assertTrue(any(c["kind"].startswith("entry:") for c in cands))

    def test_triage_returns_findings_and_done(self):
        self.triage.build_llm = lambda *a, **k: _StubLLM()
        out = self.triage.triage_specialist("injection", "аудит")
        self.assertTrue(out["raw_findings"])
        cov = out["coverage"][0]
        self.assertEqual(cov.status, "done")            # все кандидаты в бюджете
        self.assertIn("оттриажено", cov.note)

    def test_budget_zero_gives_partial_coverage(self):
        self.triage.build_llm = lambda *a, **k: _StubLLM()
        CONFIG.triage_budget_sec = 0                    # бюджет исчерпан сразу
        out = self.triage.triage_specialist("injection", "аудит")
        self.assertEqual(out["raw_findings"], [])
        cov = out["coverage"][0]
        self.assertEqual(cov.status, "partial")
        self.assertIn("вне бюджета", cov.note)

    def test_partial_result_preserved_when_a_batch_fails(self):
        # Падение 2-го батча не должно обнулять находки 1-го и 3-го.
        self.triage.build_llm = lambda *a, **k: _StubLLM(fail_on_call=2)
        out = self.triage.triage_specialist("injection", "аудит")
        self.assertGreaterEqual(len(out["raw_findings"]), 1)  # не пусто

    def test_extract_json_array(self):
        self.assertEqual(self.triage._extract_json_array("шум [1,2] хвост"),
                         [1, 2])
        self.assertEqual(self.triage._extract_json_array("нет массива"), [])


if __name__ == "__main__":
    unittest.main()
