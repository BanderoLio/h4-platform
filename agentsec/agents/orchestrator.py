"""Агент-оркестратор — точка входа системы.

Принимает задачу от человека, проводит разведку через миньонов, при
неоднозначности задаёт вопросы пользователю, делегирует работу
специалистам по классам уязвимостей и консолидирует итоговый отчёт.
"""
from __future__ import annotations

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.prebuilt import create_react_agent

from ..config import CONFIG, elapsed
from ..llm import build_llm
from ..prompts import ORCHESTRATOR_PROMPT
from ..tools.filesystem import glob_files, grep, list_dir, read_file
from ..tools.interaction import ask_user
from .minions import make_minion_tools
from .specialists import make_specialist_tools


def build_orchestrator():
    """Собирает граф оркестратора со всеми инструментами и сабагентами."""
    llm = build_llm()
    # Оркестратор только читает и координирует: чтение + вопрос пользователю
    # + миньоны для разведки + специалисты для делегирования.
    tools = [read_file, list_dir, glob_files, grep, ask_user]
    tools += make_minion_tools()
    tools += make_specialist_tools()
    return create_react_agent(llm, tools, prompt=ORCHESTRATOR_PROMPT)


def _trace(msg) -> None:
    """Печатает компактный след работы оркестратора по шагам с отметкой времени."""
    t = elapsed()
    if isinstance(msg, AIMessage):
        for tc in msg.tool_calls or []:
            args = ", ".join(f"{k}={str(v)[:80]}" for k, v in tc["args"].items())
            print(f"[+{t}]   [оркестратор → {tc['name']}]  {args}")
        if msg.content and not msg.tool_calls:
            print(f"[+{t}]   [оркестратор: формирует итоговый отчёт]")
    elif isinstance(msg, ToolMessage):
        preview = " ".join(str(msg.content or "").split())[:140]
        print(f"[+{t}]   [{msg.name} → результат]  {preview} ...")


def run(task: str) -> str:
    """Запускает анализ со стримингом шагов и возвращает итоговый markdown-отчёт."""
    orchestrator = build_orchestrator()
    final = ""
    for chunk in orchestrator.stream(
        {"messages": [("user", task)]},
        {"recursion_limit": CONFIG.recursion_limit},
        stream_mode="updates",
    ):
        for update in chunk.values():
            if not isinstance(update, dict):
                continue
            for msg in update.get("messages", []):
                _trace(msg)
                if isinstance(msg, AIMessage) and msg.content and not msg.tool_calls:
                    final = msg.content
    return final
