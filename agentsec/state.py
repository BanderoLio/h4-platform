"""Состояние графа анализа.

`AnalysisState` течёт через узлы `graph.py`. Поля-аккумуляторы помечены
reducer-ом `operator.add`: параллельные специалисты дописывают в них
свои находки и отметки покрытия без гонок. Скалярные поля пишет ровно
один узел, поэтому reducer им не нужен.
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from .schema import Coverage, Finding


class AnalysisState(TypedDict, total=False):
    # --- вход ---
    task: str                        # исходная задача от пользователя
    repo: str                        # путь к анализируемому репозиторию

    # --- intake / clarify ---
    scope: dict[str, Any]            # интерпретация задачи (intake)
    needs_clarification: bool        # требуется ли вопрос пользователю
    clarifying_question: str         # вопрос, сформулированный intake
    clarifications: list[dict]       # история Q&A с пользователем

    # --- index / recon ---
    repo_map_summary: dict[str, Any]  # сводка Repo Map (см. agentsec/index)
    recon: str                       # сводка разведки для специалистов
    scanner_outputs: dict[str, str]  # сырой вывод детерминистических сканеров

    # --- специалисты (аккумулируются параллельно) ---
    raw_findings: Annotated[list[Finding], operator.add]
    coverage: Annotated[list[Coverage], operator.add]
    errors: Annotated[list[str], operator.add]

    # --- consolidate / validate ---
    findings: list[Finding]              # дедуплицированы и пронумерованы
    validated_findings: list[Finding]    # после агента-валидатора

    # --- gate / report ---
    verdict: dict[str, Any]          # результат compute_verdict + решение gate
    report_md: str                   # итоговый markdown-отчёт
