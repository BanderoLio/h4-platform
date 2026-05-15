"""Оркестратор системы — тонкая обёртка над детерминированным графом.

Управление потоком вынесено в `agentsec.graph` (StateGraph): recon →
параллельные специалисты → consolidate → validate → gate → report.
Здесь — только запуск графа и возврат итогового состояния.
"""
from __future__ import annotations

from typing import Any

from ..config import CONFIG
from ..graph import build_graph


def run_analysis(task: str) -> dict[str, Any]:
    """Запускает анализ и возвращает итоговое состояние графа.

    В состоянии: `report_md` (итоговый markdown), `validated_findings`
    (структурные `Finding`), `verdict` (результат quality gate),
    `coverage` (что проанализировано, где пробелы).
    """
    graph = build_graph()
    initial = {"task": task, "repo": str(CONFIG.analysis_root)}
    # recursion_limit с запасом: граф плоский, но specialist-узлы внутри
    # запускают ReAct-агентов — лимит ограничивает их собственные шаги.
    final_state = graph.invoke(initial, {"recursion_limit": CONFIG.recursion_limit})
    return final_state


def run(task: str) -> str:
    """Совместимость: запускает анализ и возвращает только markdown-отчёт."""
    return run_analysis(task).get("report_md", "")
