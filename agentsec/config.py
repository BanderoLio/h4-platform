"""Глобальная конфигурация рантайма.

Один экземпляр CONFIG создаётся при импорте и мутируется из main.py
перед запуском оркестратора (например, выставляется корень анализа).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    # Корень анализируемого репозитория. Все файловые инструменты работают внутри него.
    analysis_root: Path = field(default_factory=Path.cwd)
    # Лимит вывода read_file в символах — защита контекста от огромных файлов.
    read_file_max_chars: int = 20_000
    # Лимит шагов одного графа агента — защита от циклов agent -> agent -> minion.
    recursion_limit: int = 60
    # True -> write/edit не спрашивают подтверждение (неинтерактивные прогоны).
    auto_approve_writes: bool = False
    # Момент старта анализа (monotonic) — для подсчёта прошедшего времени.
    started_at: float = field(default_factory=time.monotonic)

    # --- оркестрация графа ---
    # Интерактивный режим: можно задавать вопросы пользователю (intake/gate).
    interactive: bool = True
    # Запускать детерминистические сканеры в фазе recon.
    run_scanners: bool = False
    # Сколько раз ретраить узел-специалист при ошибке или пустом результате.
    specialist_retries: int = 1
    # Стаб-режим: специалисты возвращают пустой результат (сборка/тест без B).
    stub_specialists: bool = False
    # Параллелизм валидатора: находки проверяются пулом потоков.
    validator_max_workers: int = 4
    # Лимит шагов ReAct-агента валидатора на одну находку (защита от петель).
    validator_recursion_limit: int = 18

    # --- quality gate ---
    # Severity, при которых подтверждённая находка блокирует сборку.
    gate_fail_severities: tuple[str, ...] = ("Critical", "High")


CONFIG = Config()


def elapsed() -> str:
    """Время с момента старта анализа в формате M:SS."""
    secs = int(time.monotonic() - CONFIG.started_at)
    return f"{secs // 60}:{secs % 60:02d}"
