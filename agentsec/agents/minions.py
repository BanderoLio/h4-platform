"""Сабагенты-миньоны — узкоспециализированные исполнители.

Миньоны доступны и оркестратору, и специалистам. Каждый миньон —
самостоятельный ReAct-граф; наружу он отдаётся как инструмент-обёртка,
чтобы вышестоящий агент мог «вызвать миньона».
"""
from __future__ import annotations

import time

from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from ..config import CONFIG, elapsed
from ..llm import build_llm
from ..prompts import DOCS_PROMPT, EXPLORER_PROMPT
from ..tools.filesystem import glob_files, grep, list_dir, read_file

# Миньоны работают только на чтение.
_READ_TOOLS = [read_file, list_dir, glob_files, grep]


def make_minion_tools() -> list:
    """Создаёт миньонов и возвращает список инструментов-обёрток над ними."""
    llm = build_llm()
    explorer = create_react_agent(llm, _READ_TOOLS, prompt=EXPLORER_PROMPT)
    docs = create_react_agent(llm, _READ_TOOLS, prompt=DOCS_PROMPT)
    run_cfg = {"recursion_limit": CONFIG.recursion_limit}

    def _run_minion(agent, label: str, query: str) -> str:
        t0 = time.perf_counter()
        print(f"[+{elapsed()}]       .. миньон {label} запущен")
        try:
            result = agent.invoke({"messages": [("user", query)]}, run_cfg)
            out = result["messages"][-1].content
        except Exception as err:  # noqa: BLE001 — сбой миньона не должен ронять прогон
            dt = time.perf_counter() - t0
            print(f"[+{elapsed()}]       !! миньон {label} упал за {dt:.0f}с: {err}")
            return f"[Миньон '{label}' не смог выполнить запрос из-за ошибки: {err}]"
        dt = time.perf_counter() - t0
        print(f"[+{elapsed()}]       .. миньон {label} завершил за {dt:.0f}с")
        return out

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

    return [explore_codebase, read_docs]
