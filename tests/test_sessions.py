"""Тесты персистентности сессий: хранилище + пауза/возобновление графа.

Сеть не используется: LLM, миньоны и специалисты подменены стабами,
как в `test_graph_smoke`. Проверяется проводка чекпоинтера и `interrupt()`.
"""
from __future__ import annotations

import tempfile
import unittest
import uuid
from pathlib import Path

from langgraph.types import Command

from agentsec import graph as G
from agentsec.agents.orchestrator import interrupt_value
from agentsec.config import CONFIG
from agentsec.persistence.checkpointer import make_checkpointer
from agentsec.persistence.store import (
    STATUS_AWAITING_INPUT,
    STATUS_COMPLETED,
    SessionRecord,
    SqliteSessionStore,
)


class _FakeReply:
    def __init__(self, content: str) -> None:
        self.content = content


class _ClarifyLLM:
    """Стаб-LLM intake: всегда требует уточнения скоупа."""

    def invoke(self, _messages):
        return _FakeReply(
            '{"focus": ["injection"], "needs_clarification": true, '
            '"scope_summary": "stub", "clarifying_question": "Какой модуль?"}'
        )


class _FakeMinion:
    def __init__(self, name: str) -> None:
        self.name = name

    def invoke(self, _payload: dict) -> str:
        return f"[стаб-миньон {self.name}]"


# --- хранилище ---------------------------------------------------------------

class StoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = SqliteSessionStore(Path(self._tmp.name) / "s.db")

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def test_create_get_roundtrip(self):
        rec = SessionRecord(
            id="a1", title="t", repo="/r", task="task",
            interrupt_payload={"type": "clarify", "question": "Q?"},
        )
        self.store.create_session(rec)
        got = self.store.get_session("a1")
        self.assertIsNotNone(got)
        # JSON-поле восстановилось как dict.
        self.assertEqual(got.interrupt_payload["question"], "Q?")
        self.assertIsNone(self.store.get_session("missing"))

    def test_list_newest_first(self):
        self.store.create_session(SessionRecord(
            id="old", title="o", repo="/r", task="t",
            created_at="2026-01-01T00:00:00+00:00"))
        self.store.create_session(SessionRecord(
            id="new", title="n", repo="/r", task="t",
            created_at="2026-05-01T00:00:00+00:00"))
        ids = [s.id for s in self.store.list_sessions()]
        self.assertEqual(ids, ["new", "old"])
        # Пагинация.
        self.assertEqual(
            [s.id for s in self.store.list_sessions(limit=1, offset=1)], ["old"])

    def test_update_session(self):
        self.store.create_session(SessionRecord(
            id="u1", title="t", repo="/r", task="t"))
        self.store.update_session(
            "u1", status=STATUS_COMPLETED, verdict={"verdict": "PASS"})
        got = self.store.get_session("u1")
        self.assertEqual(got.status, STATUS_COMPLETED)
        self.assertEqual(got.verdict["verdict"], "PASS")
        with self.assertRaises(ValueError):
            self.store.update_session("u1", bogus_field=1)


# --- пауза графа и возобновление --------------------------------------------

class InterruptResumeTest(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = (
            CONFIG.stub_specialists, CONFIG.interactive, CONFIG.run_scanners,
            CONFIG.server_mode, CONFIG.analysis_root,
            G.build_llm, G.make_validator_node,
        )
        CONFIG.stub_specialists = True
        CONFIG.run_scanners = False
        CONFIG.interactive = True   # вопросы задаём…
        CONFIG.server_mode = True   # …и ставим граф на паузу через interrupt()
        self._idx_tmp = tempfile.TemporaryDirectory()
        CONFIG.analysis_root = Path(self._idx_tmp.name)  # узел index → пустой каталог
        G.build_llm = lambda *a, **k: _ClarifyLLM()
        G.make_validator_node = lambda: (
            lambda state: {"validated_findings": state.get("findings", [])}
        )
        import agentsec.agents.minions as minions_mod

        self._saved_minions = minions_mod.make_minion_tools
        minions_mod.make_minion_tools = lambda: [
            _FakeMinion("explore_codebase"), _FakeMinion("read_docs")
        ]
        self._tmp = tempfile.TemporaryDirectory()
        self._db = Path(self._tmp.name) / f"cp-{uuid.uuid4().hex}.db"

    def tearDown(self) -> None:
        (CONFIG.stub_specialists, CONFIG.interactive, CONFIG.run_scanners,
         CONFIG.server_mode, CONFIG.analysis_root,
         G.build_llm, G.make_validator_node) = self._saved
        import agentsec.agents.minions as minions_mod

        minions_mod.make_minion_tools = self._saved_minions
        self._tmp.cleanup()
        self._idx_tmp.cleanup()

    def test_pause_at_clarify_then_gate_then_complete(self):
        graph = G.build_graph(checkpointer=make_checkpointer(self._db))
        config = {"configurable": {"thread_id": "sess-1"},
                  "recursion_limit": 40}

        # 1) Старт → пауза на уточняющем вопросе.
        st1 = graph.invoke({"task": "Проверь", "repo": "/tmp/x"}, config)
        pause1 = interrupt_value(st1)
        self.assertIsNotNone(pause1)
        self.assertEqual(pause1["type"], "clarify")
        self.assertEqual(pause1["question"], "Какой модуль?")

        # 2) Ответ пользователя → граф идёт дальше, пауза на gate.
        st2 = graph.invoke(Command(resume="модуль auth"), config)
        pause2 = interrupt_value(st2)
        self.assertIsNotNone(pause2)
        self.assertEqual(pause2["type"], "gate")

        # 3) Решение gate → граф доходит до END.
        st3 = graph.invoke(Command(resume="да"), config)
        self.assertIsNone(interrupt_value(st3))
        self.assertIn("report_md", st3)
        self.assertIn("# Отчёт анализа безопасности", st3["report_md"])
        # Ответ на уточнение сохранён в состоянии.
        clar = st3.get("clarifications", [])
        self.assertEqual(clar[0]["answer"], "модуль auth")
        self.assertTrue(st3["verdict"]["approved_for_build"])

    def test_resume_survives_fresh_graph_object(self):
        """Возобновление работает на новом объекте графа — состояние в SQLite."""
        config = {"configurable": {"thread_id": "sess-2"},
                  "recursion_limit": 40}
        g1 = G.build_graph(checkpointer=make_checkpointer(self._db))
        st1 = g1.invoke({"task": "Проверь", "repo": "/tmp/x"}, config)
        self.assertEqual(interrupt_value(st1)["type"], "clarify")

        # Новый объект графа, тот же файл-чекпоинтер и thread_id.
        g2 = G.build_graph(checkpointer=make_checkpointer(self._db))
        st2 = g2.invoke(Command(resume="любой"), config)
        self.assertEqual(interrupt_value(st2)["type"], "gate")


# --- фасад сессий: очередь воркера + переходы статуса -----------------------

class FacadeTest(unittest.TestCase):
    """Проверяет agentsec.session: start/resume через фоновый воркер.

    `run_analysis` подменён — фасад тестируется без графа и сети: важны
    проводка очереди, переходы статуса и запись результата в хранилище.
    """

    def setUp(self) -> None:
        import agentsec.session as sess

        self.sess = sess
        self._tmp = tempfile.TemporaryDirectory()
        self._saved_db = CONFIG.session_db_path
        self._saved_root = CONFIG.analysis_root
        self._saved_run = sess.run_analysis
        # Изолированная БД на тест, сброс кешированного хранилища.
        CONFIG.session_db_path = Path(self._tmp.name) / f"s-{uuid.uuid4().hex}.db"
        sess._store = None

    def tearDown(self) -> None:
        CONFIG.session_db_path = self._saved_db
        CONFIG.analysis_root = self._saved_root
        self.sess.run_analysis = self._saved_run
        self.sess._store = None
        self._tmp.cleanup()

    def test_start_session_runs_and_completes(self):
        self.sess.run_analysis = lambda **kw: {
            "verdict": {"verdict": "PASS"}, "report_md": "# отчёт"}
        sid = self.sess.start_session("аудит проекта", self._tmp.name)
        self.sess._jobs.join()  # ждём фоновый воркер
        rec = self.sess.get_session(sid)
        self.assertEqual(rec.status, STATUS_COMPLETED)
        self.assertEqual(rec.verdict["verdict"], "PASS")
        self.assertEqual(rec.report_md, "# отчёт")

    def test_pause_then_resume_via_facade(self):
        def _fake(**kw):
            if kw.get("resume") is None:
                return {"__interrupt__": [
                    {"type": "clarify", "question": "Какой модуль?"}]}
            return {"verdict": {"verdict": "FAIL"}, "report_md": "# готово"}

        self.sess.run_analysis = _fake
        sid = self.sess.start_session("аудит", self._tmp.name)
        self.sess._jobs.join()
        rec = self.sess.get_session(sid)
        self.assertEqual(rec.status, STATUS_AWAITING_INPUT)
        self.assertEqual(rec.interrupt_type, "clarify")
        self.assertEqual(rec.interrupt_payload["question"], "Какой модуль?")

        self.sess.resume_session(sid, "модуль авторизации")
        self.sess._jobs.join()
        rec = self.sess.get_session(sid)
        self.assertEqual(rec.status, STATUS_COMPLETED)
        self.assertEqual(rec.verdict["verdict"], "FAIL")

    def test_resume_rejected_when_not_awaiting(self):
        self.sess.run_analysis = lambda **kw: {
            "verdict": {"verdict": "PASS"}, "report_md": "ok"}
        sid = self.sess.start_session("аудит", self._tmp.name)
        self.sess._jobs.join()
        # Сессия уже completed — resume должен быть отвергнут (бэкенд -> 409).
        with self.assertRaises(ValueError):
            self.sess.resume_session(sid, "поздно")

    def test_start_session_validates_input(self):
        with self.assertRaises(ValueError):
            self.sess.start_session("", self._tmp.name)
        with self.assertRaises(ValueError):
            self.sess.start_session("задача", "/no/such/dir/xyz")


if __name__ == "__main__":
    unittest.main()
