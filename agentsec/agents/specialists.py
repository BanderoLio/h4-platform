"""Агенты-специалисты по классам уязвимостей.

Каждый специалист — самостоятельный ReAct-граф с файловыми инструментами
и доступом к миньонам. Наружу отдаётся как инструмент-обёртка, чтобы
оркестратор мог делегировать ему работу.
"""
from __future__ import annotations

import time

from langchain_core.tools import tool
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
from .minions import make_minion_tools


def make_specialist_tools() -> list:
    """Создаёт трёх специалистов и возвращает инструменты-обёртки для оркестратора."""
    llm = build_llm()
    # Специалистам доступно: чтение, запись (тесты/PoC), редактирование, миньоны.
    base_tools = [read_file, write_file, edit_file, list_dir, glob_files, grep]
    tools = base_tools + make_minion_tools()
    run_cfg = {"recursion_limit": CONFIG.recursion_limit}

    injection = create_react_agent(llm, tools, prompt=INJECTION_PROMPT)
    secrets = create_react_agent(llm, tools, prompt=SECRETS_PROMPT)
    authnz = create_react_agent(llm, tools, prompt=AUTHNZ_PROMPT)

    def _run(agent, label: str, task: str) -> str:
        t0 = time.perf_counter()
        print(f"[+{elapsed()}]     >> специалист [{label}] запущен")
        try:
            result = agent.invoke({"messages": [("user", task)]}, run_cfg)
            out = result["messages"][-1].content
        except Exception as err:  # noqa: BLE001 — сбой спеца не должен ронять прогон
            dt = time.perf_counter() - t0
            print(f"[+{elapsed()}]     !! специалист [{label}] упал за {dt:.0f}с: {err}")
            return f"[Специалист '{label}' не завершил анализ из-за ошибки: {err}]"
        dt = time.perf_counter() - t0
        print(f"[+{elapsed()}]     << специалист [{label}] завершил за {dt:.0f}с, "
              f"отчёт {len(out)} симв.")
        return out

    @tool
    def analyze_injections(task: str) -> str:
        """Специалист по инъекциям: SQLi, command injection, path traversal,
        SSRF, XSS, небезопасная десериализация, template injection.
        В task передай контекст из разведки: стек, точки входа, что смотреть."""
        return _run(injection, "инъекции", task)

    @tool
    def analyze_secrets_crypto(task: str) -> str:
        """Специалист по секретам и криптографии: хардкод-секреты, токены,
        слабые/устаревшие алгоритмы, плохой ГПСЧ, ошибки работы с ключами.
        В task передай контекст из разведки: где конфиги, стек, что смотреть."""
        return _run(secrets, "секреты/крипто", task)

    @tool
    def analyze_authnz(task: str) -> str:
        """Специалист по аутентификации и авторизации: обход аутентификации,
        broken access control, IDOR, небезопасные сессии, privilege escalation.
        В task передай контекст из разведки: где эндпоинты, модель доступа."""
        return _run(authnz, "authn/authz", task)

    return [analyze_injections, analyze_secrets_crypto, analyze_authnz]
