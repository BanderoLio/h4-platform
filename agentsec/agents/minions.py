"""Сабагенты-миньоны — узкоспециализированные исполнители.

Миньоны доступны и оркестратору, и специалистам. Каждый миньон —
самостоятельный ReAct-граф; наружу он отдаётся как инструмент-обёртка,
чтобы вышестоящий агент мог «вызвать миньона».
"""
from __future__ import annotations

import threading
import time

from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from ..config import CONFIG, elapsed
from ..llm import build_llm
from ..prompts import (
    CALLGRAPH_PROMPT,
    CVE_PROMPT,
    DEPENDENCY_PROMPT,
    DOCS_PROMPT,
    EXPLORER_PROMPT,
)
from ..tools.callgraph import build_callgraph
from ..tools.dependencies import resolve_dependencies, search_dependency_cves
from ..tools.filesystem import glob_files, grep, list_dir, read_file
from ..tools.scanners import run_gitleaks, run_osv_scanner, run_semgrep

# Миньоны работают только на чтение.
_READ_TOOLS = [read_file, list_dir, glob_files, grep]


def make_minion_tools() -> list:
    """Создаёт миньонов и возвращает список инструментов-обёрток над ними."""
    llm = build_llm()
    explorer = create_react_agent(llm, _READ_TOOLS, prompt=EXPLORER_PROMPT)
    docs = create_react_agent(llm, _READ_TOOLS, prompt=DOCS_PROMPT)
    dependency = create_react_agent(
        llm,
        _READ_TOOLS + [resolve_dependencies, run_osv_scanner],
        prompt=DEPENDENCY_PROMPT,
    )
    cve = create_react_agent(
        llm,
        [resolve_dependencies, search_dependency_cves, run_osv_scanner],
        prompt=CVE_PROMPT,
    )
    callgraph = create_react_agent(
        llm,
        _READ_TOOLS + [build_callgraph, run_semgrep],
        prompt=CALLGRAPH_PROMPT,
    )
    run_cfg = {"recursion_limit": CONFIG.recursion_limit}

    def _run_minion(agent, label: str, query: str) -> str:
        t0 = time.perf_counter()
        print(f"[+{elapsed()}]       .. миньон {label} запущен")
        # ReAct-петлю гоним в daemon-потоке: join с таймаутом даёт жёсткий
        # лимит времени. У миниона нет внешней recursion-границы, без
        # таймаута он может идти неограниченно (на большом репо — минуты).
        box: dict = {}

        def _work() -> None:
            try:
                result = agent.invoke({"messages": [("user", query)]}, run_cfg)
                box["out"] = result["messages"][-1].content
            except Exception as err:  # noqa: BLE001
                box["error"] = err

        worker = threading.Thread(target=_work, daemon=True)
        worker.start()
        worker.join(CONFIG.minion_timeout_sec)
        dt = time.perf_counter() - t0
        if worker.is_alive():
            print(f"[+{elapsed()}]       !! миньон {label} превысил лимит "
                  f"{CONFIG.minion_timeout_sec}с — прерван")
            return (f"[Миньон '{label}' превысил лимит "
                    f"{CONFIG.minion_timeout_sec}с и был прерван]")
        if "error" in box:
            print(f"[+{elapsed()}]       !! миньон {label} упал за "
                  f"{dt:.0f}с: {box['error']}")
            return (f"[Миньон '{label}' не смог выполнить запрос из-за "
                    f"ошибки: {box['error']}]")
        print(f"[+{elapsed()}]       .. миньон {label} завершил за {dt:.0f}с")
        return box["out"]

    @tool
    def explore_codebase(query: str) -> str:
        """Миньон-разведчик. Делегируй ему разведку кодовой базы: структуру
        проекта, стек, точки входа, поиск где расположен нужный паттерн.
        В query опиши, что именно нужно выяснить."""
        return _run_minion(explorer, "explore_codebase", query)

    @tool
    def read_docs(query: str) -> str:
        """Миньон по документации. Делегируй ему чтение README, docs/ и
        конфигов, чтобы понять назначение модуля, как запускается проект,
        заявленную модель безопасности. В query опиши, что нужно узнать."""
        return _run_minion(docs, "read_docs", query)

    @tool
    def resolve_project_dependencies(query: str) -> str:
        """Миньон по зависимостям. Разбирает requirements.txt, package.json,
        lock-файлы и go.mod, выделяет экосистемы, версии и места объявления."""
        return _run_minion(dependency, "resolve_project_dependencies", query)

    @tool
    def search_dependency_vulnerabilities(query: str) -> str:
        """Миньон CVE/OSV-поиска по зависимостям. Используй для проверки
        известных уязвимостей в пакетах и lock-файлах проекта."""
        return _run_minion(cve, "search_dependency_vulnerabilities", query)

    @tool
    def sketch_callgraph(query: str) -> str:
        """Миньон грубого callgraph. Помогает найти вероятные вызовы,
        source->sink цепочки и файлы для ручной проверки специалистами."""
        return _run_minion(callgraph, "sketch_callgraph", query)

    @tool
    def run_deterministic_scanners(query: str) -> str:
        """Запускает semgrep, gitleaks и osv-scanner, если они установлены.
        Возвращает JSON/coverage-статус; отсутствующие CLI не считаются падением."""
        print(f"[+{elapsed()}]       .. сканеры запущены: {query[:100]}")
        outputs = [
            ("semgrep", run_semgrep.invoke({"config": "auto"})),
            ("gitleaks", run_gitleaks.invoke({})),
            ("osv-scanner", run_osv_scanner.invoke({})),
        ]
        return "\n\n".join(f"## {name}\n{output}" for name, output in outputs)

    return [
        explore_codebase,
        read_docs,
        resolve_project_dependencies,
        search_dependency_vulnerabilities,
        sketch_callgraph,
        run_deterministic_scanners,
    ]
