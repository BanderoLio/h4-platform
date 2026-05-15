"""Агенты-специалисты по классам уязвимостей.

Каждый специалист — самостоятельный ReAct-граф с файловыми инструментами
и доступом к миньонам. Наружу отдаётся как callable `(task) -> markdown`,
который узлы графа `graph.py` оборачивают в `Finding` через
`schema.parse_findings_markdown`.
"""
from __future__ import annotations

import time
from typing import Callable

from langgraph.prebuilt import create_react_agent

from ..config import CONFIG, elapsed
from ..llm import build_llm
from ..prompts import AUTHNZ_PROMPT, INJECTION_PROMPT, SECRETS_PROMPT
from ..tools.filesystem import (
    edit_file,
    glob_files,
    grep,
    list_dir,
    read_file,
    write_file,
)
from ..tools.scanners import run_gitleaks, run_osv_scanner, run_semgrep
from .minions import make_minion_tools

# Человекочитаемые ярлыки специалистов по классу уязвимостей.
SPECIALIST_LABELS = {
    "injection": "инъекции",
    "secrets": "секреты/крипто",
    "authnz": "authn/authz",
}


def make_specialist_runners() -> dict[str, Callable[[str], str]]:
    """Создаёт трёх специалистов и возвращает callables `(task) -> markdown`.

    Узлы графа вызывают эти функции напрямую — детерминированно, без того
    чтобы LLM-оркестратор решал, кого запускать.
    """
    llm = build_llm()
    # Специалистам доступно: чтение, запись (тесты/PoC), редактирование, миньоны.
    base_tools = [
        read_file,
        write_file,
        edit_file,
        list_dir,
        glob_files,
        grep,
        run_semgrep,
        run_gitleaks,
        run_osv_scanner,
    ]
    tools = base_tools + make_minion_tools()
    run_cfg = {"recursion_limit": CONFIG.recursion_limit}

    agents = {
        "injection": create_react_agent(llm, tools, prompt=INJECTION_PROMPT),
        "secrets": create_react_agent(llm, tools, prompt=SECRETS_PROMPT),
        "authnz": create_react_agent(llm, tools, prompt=AUTHNZ_PROMPT),
    }

    def _make_runner(vuln_class: str) -> Callable[[str], str]:
        agent = agents[vuln_class]
        label = SPECIALIST_LABELS[vuln_class]

        def _run(task: str) -> str:
            t0 = time.perf_counter()
            print(f"[+{elapsed()}]     >> специалист [{label}] запущен")
            try:
                result = agent.invoke({"messages": [("user", task)]}, run_cfg)
                out = result["messages"][-1].content or ""
            except Exception as err:  # noqa: BLE001 — сбой спеца не роняет граф
                dt = time.perf_counter() - t0
                print(f"[+{elapsed()}]     !! специалист [{label}] упал за "
                      f"{dt:.0f}с: {err}")
                raise
            dt = time.perf_counter() - t0
            print(f"[+{elapsed()}]     << специалист [{label}] завершил за "
                  f"{dt:.0f}с, отчёт {len(out)} симв.")
            return out

        return _run

    return {vuln_class: _make_runner(vuln_class) for vuln_class in agents}
