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
    # Жёсткий лимит времени на одного специалиста (сек). Гарантирует
    # адекватное время прогона: ReAct-петля специалиста на большом репо
    # иначе ничем, кроме recursion_limit, не ограничена.
    specialist_timeout_sec: int = 240
    # Сколько кандидатов из Repo Map подаётся специалисту на триаж.
    # Бюджет контекста: на большом репо список sink-ов/точек входа
    # обрезается, остаток помечается как непокрытый.
    max_candidates_per_specialist: int = 60
    # Стаб-режим: специалисты возвращают пустой результат (сборка/тест без B).
    stub_specialists: bool = False
    # --- триаж-воркер (специалист как детерминированный триажёр) ---
    # Кандидатов в одном LLM-вызове батч-триажа.
    triage_batch_size: int = 8
    # Бюджет времени на триаж одного класса (сек). Батчи идут по очереди,
    # результат каждого коммитится — по исчерпании бюджета цикл
    # останавливается, накопленные находки сохраняются (инкрементально).
    triage_budget_sec: int = 200
    # Жёсткий лимит времени на один батч триажа (сек) — страховка от
    # патологического батча (огромный промпт), который иначе не даёт
    # сработать межбатчевой проверке бюджета.
    triage_batch_timeout_sec: int = 90
    # Жёсткий лимит времени на один минион (сек) — у миниона нет
    # recursion-петли наружу, без таймаута он может идти неограниченно.
    minion_timeout_sec: int = 100
    # Репо крупнее этого числа файлов считается большим: recon пропускает
    # explore-миньон (Repo Map уже даёт структуру детерминированно).
    explore_skip_files: int = 400
    # Параллелизм валидатора: находки проверяются пулом потоков.
    validator_max_workers: int = 4
    # Лимит шагов ReAct-агента валидатора на одну находку (защита от петель).
    validator_recursion_limit: int = 18

    # --- quality gate ---
    # Severity, при которых подтверждённая находка блокирует сборку.
    gate_fail_severities: tuple[str, ...] = ("Critical", "High")

    # --- сессии и персистентность (server-режим для FastAPI-бэкенда) ---
    # True -> узлы _clarify/_gate ставят граф на паузу через interrupt()
    # вместо чтения ответа из stdin. CLI его не выставляет: поведение
    # консоли не меняется. interactive решает «задавать ли вопрос»,
    # server_mode — «как задавать» (HTTP-пауза vs stdin).
    server_mode: bool = False
    # Единый SQLite-файл: и чекпоинтер LangGraph, и таблица sessions.
    session_db_path: Path = field(default_factory=lambda: Path("agentsec_sessions.db"))
    # Флаг Фазы 2 (дозапросы по завершённому скану). По умолчанию выкл.
    enable_followup: bool = False


CONFIG = Config()


def elapsed() -> str:
    """Время с момента старта анализа в формате M:SS."""
    secs = int(time.monotonic() - CONFIG.started_at)
    return f"{secs // 60}:{secs % 60:02d}"
