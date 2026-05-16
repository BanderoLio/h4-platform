"""Оркестратор системы — тонкая обёртка над детерминированным графом.

Управление потоком вынесено в `agentsec.graph` (StateGraph): recon →
параллельные специалисты → consolidate → validate → gate → report → patches.
Здесь — только запуск/возобновление графа и возврат итогового состояния.

Два режима вызова:
* старт нового анализа — передаётся `task`;
* возобновление сессии — передаётся `thread_id` и `resume` (ответ
  пользователя на паузу `interrupt()`).

Чекпоинтер нужен только для server-режима (паузы и история сессий).
CLI вызывает `run_analysis(task)` без `thread_id`/`checkpointer` —
поведение полностью совпадает с прежним.
"""
from __future__ import annotations

from typing import Any

from langgraph.types import Command

from ..config import CONFIG
from ..graph import build_graph


def run_analysis(
    task: str | None = None,
    *,
    thread_id: str | None = None,
    resume: str | None = None,
    checkpointer: Any = None,
) -> dict[str, Any]:
    """Запускает или возобновляет анализ, возвращает состояние графа.

    В состоянии: `report_md` (итоговый markdown), `validated_findings`
    (структурные `Finding`), `fix_patches` (candidate unified diff),
    `verdict` (результат quality gate), `coverage` (что проанализировано,
    где пробелы). Если граф встал на паузу `interrupt()`, в состоянии будет
    ключ `__interrupt__` — см. `interrupt_value()`.
    """
    graph = build_graph(checkpointer=checkpointer)
    # recursion_limit с запасом: граф плоский, но specialist-узлы внутри
    # запускают ReAct-агентов — лимит ограничивает их собственные шаги.
    config: dict[str, Any] = {"recursion_limit": CONFIG.recursion_limit}
    if thread_id is not None:
        config["configurable"] = {"thread_id": thread_id}

    if resume is not None:
        # Возобновление: LangGraph поднимает состояние из чекпоинта по
        # thread_id и продолжает с узла, вставшего на interrupt().
        return graph.invoke(Command(resume=resume), config)
    return graph.invoke({"task": task, "repo": str(CONFIG.analysis_root)}, config)


def interrupt_value(state: dict[str, Any]) -> dict[str, Any] | None:
    """Достаёт payload паузы из состояния графа или None, если паузы нет.

    LangGraph кладёт в `__interrupt__` список объектов `Interrupt`;
    нас интересует значение первого — словарь, переданный в `interrupt()`
    (`{"type": "clarify"|"gate", "question": ..., ...}`).
    """
    interrupts = state.get("__interrupt__")
    if not interrupts:
        return None
    first = interrupts[0]
    value = getattr(first, "value", first)
    return value if isinstance(value, dict) else {"value": value}


def run(task: str) -> str:
    """Совместимость: запускает анализ и возвращает только markdown-отчёт."""
    return run_analysis(task).get("report_md", "")
