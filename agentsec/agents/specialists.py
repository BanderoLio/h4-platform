"""Агенты-специалисты по классам уязвимостей.

Каждый специалист — самостоятельный ReAct-граф с файловыми инструментами
и доступом к миньонам. Наружу отдаётся как callable `(task) -> markdown`,
который узлы графа `graph.py` оборачивают в `Finding` через
`schema.parse_findings_markdown`.
"""
from __future__ import annotations

import threading
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
from ..tools.repomap import repo_map_tools
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
    # Repo Map: специалист идёт от точек входа к sink-ам по индексу,
    # а не обходит репозиторий слепым grep.
    tools = base_tools + repo_map_tools() + make_minion_tools()
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
            # ReAct-петля исполняется в отдельном потоке: join с таймаутом
            # даёт жёсткий лимит времени. Поток daemon — зависший вызов не
            # держит процесс на выходе (его токены просто отбрасываются).
            box: dict = {}

            def _work() -> None:
                try:
                    box["result"] = agent.invoke(
                        {"messages": [("user", task)]}, run_cfg)
                except Exception as err:  # noqa: BLE001
                    box["error"] = err

            worker = threading.Thread(target=_work, daemon=True)
            worker.start()
            worker.join(CONFIG.specialist_timeout_sec)
            dt = time.perf_counter() - t0
            if worker.is_alive():
                print(f"[+{elapsed()}]     !! специалист [{label}] превысил "
                      f"лимит {CONFIG.specialist_timeout_sec}с — прерван")
                raise TimeoutError(
                    f"специалист [{label}] не уложился в "
                    f"{CONFIG.specialist_timeout_sec}с")
            if "error" in box:
                print(f"[+{elapsed()}]     !! специалист [{label}] упал за "
                      f"{dt:.0f}с: {box['error']}")
                raise box["error"]
            out = box["result"]["messages"][-1].content or ""
            print(f"[+{elapsed()}]     << специалист [{label}] завершил за "
                  f"{dt:.0f}с, отчёт {len(out)} симв.")
            return out

        return _run

    return {vuln_class: _make_runner(vuln_class) for vuln_class in agents}
