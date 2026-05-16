"""Сквозной smoke-тест графа на стаб-LLM.

Прогоняет весь граф (intake → recon → специалисты → consolidate →
validate → gate → report → patches) БЕЗ сети: LLM, миньоны и специалисты
подменены. Ловит регрессии в проводке узлов и состоянии.
"""
from __future__ import annotations

import unittest

from agentsec import graph as G
from agentsec.config import CONFIG


class _FakeReply:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeLLM:
    """Минимальный LLM: на любой запрос возвращает фиксированный JSON intake."""

    def invoke(self, _messages):
        return _FakeReply('{"focus": ["injection", "secrets", "authnz"], '
                          '"needs_clarification": false, '
                          '"scope_summary": "stub", "clarifying_question": ""}')


class _FakeMinion:
    def __init__(self, name: str) -> None:
        self.name = name

    def invoke(self, _payload: dict) -> str:
        return f"[стаб-миньон {self.name}: разведданные]"


class GraphSmokeTest(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = (
            CONFIG.stub_specialists, CONFIG.interactive, CONFIG.run_scanners,
            G.build_llm, G.make_validator_node,
        )
        # Специалисты — стабы; интерактив и сканеры выключены.
        CONFIG.stub_specialists = True
        CONFIG.interactive = False
        CONFIG.run_scanners = False
        # Подменяем сетевые зависимости графа.
        G.build_llm = lambda *a, **k: _FakeLLM()
        G.make_validator_node = lambda: (
            lambda state: {"validated_findings": state.get("findings", [])}
        )
        import agentsec.agents.minions as minions_mod

        self._saved_minions = minions_mod.make_minion_tools
        minions_mod.make_minion_tools = lambda: [
            _FakeMinion("explore_codebase"), _FakeMinion("read_docs")
        ]

    def tearDown(self) -> None:
        (CONFIG.stub_specialists, CONFIG.interactive, CONFIG.run_scanners,
         G.build_llm, G.make_validator_node) = self._saved
        import agentsec.agents.minions as minions_mod

        minions_mod.make_minion_tools = self._saved_minions

    def test_full_graph_runs_offline(self):
        compiled = G.build_graph()
        final = compiled.invoke(
            {"task": "Проверь безопасность", "repo": "/tmp/x"},
            {"recursion_limit": 40},
        )
        # Граф дошёл до конца: есть отчёт и вердикт.
        self.assertIn("report_md", final)
        self.assertIn("# Отчёт анализа безопасности", final["report_md"])
        self.assertIn("verdict", final)
        self.assertEqual(final["verdict"]["verdict"], "NEEDS_REVIEW")
        # Все три специалиста отметились в покрытии (стабы -> gap).
        areas = {c.area for c in final["coverage"]}
        for cls in ("injection", "secrets", "authnz"):
            self.assertIn(cls, areas)
        # Стаб-специалисты находок не дали.
        self.assertEqual(final.get("validated_findings", []), [])
        self.assertEqual(final.get("fix_patches", []), [])


if __name__ == "__main__":
    unittest.main()
