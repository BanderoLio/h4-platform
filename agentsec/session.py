"""Фасад жизненного цикла сессии анализа.

Единственный модуль, который импортирует внешний FastAPI-бэкенд. Связывает
три части: хранилище метаданных (`persistence.store`), чекпоинтер графа
(`persistence.checkpointer`) и оркестратор (`agents.orchestrator`). Сам
оркестратор о сессиях ничего не знает — вся «история» живёт здесь.

Модель работы:
* `start_session` / `resume_session` ставят прогон в очередь и сразу
  возвращают управление — скан идёт минуты, держать HTTP-запрос нельзя;
* фоновый воркер один: сканы выполняются строго по одному. Причина —
  `CONFIG` это глобальный мутируемый синглтон; параллельные прогоны
  затёрли бы друг другу `analysis_root`. Per-run Config — задача на потом.
* пауза графа на `interrupt()` не порождает HTTP-событие: воркер просто
  фиксирует статус `awaiting_input`, клиент узнаёт о паузе поллингом.
"""
from __future__ import annotations

import queue
import threading
import traceback
import uuid
from pathlib import Path
from typing import Any

from .agents.orchestrator import interrupt_value, run_analysis
from .config import CONFIG
from .persistence.checkpointer import make_checkpointer
from .persistence.store import (
    STATUS_AWAITING_INPUT,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_RUNNING,
    SessionRecord,
    SqliteSessionStore,
)

# --- ленивые синглтоны процесса ---------------------------------------------
_store: SqliteSessionStore | None = None
_store_lock = threading.Lock()


def _get_store() -> SqliteSessionStore:
    """Хранилище сессий (создаётся при первом обращении)."""
    global _store
    with _store_lock:
        if _store is None:
            _store = SqliteSessionStore(CONFIG.session_db_path)
        return _store


# --- фоновый воркер: один поток, очередь, сканы строго по одному -------------
_jobs: "queue.Queue[tuple]" = queue.Queue()
_worker_started = False
_worker_lock = threading.Lock()


def _worker_loop() -> None:
    while True:
        session_id, kwargs = _jobs.get()
        try:
            _run(session_id, **kwargs)
        except Exception:  # noqa: BLE001 — воркер не должен умирать
            traceback.print_exc()
        finally:
            _jobs.task_done()


def _ensure_worker() -> None:
    global _worker_started
    with _worker_lock:
        if not _worker_started:
            threading.Thread(
                target=_worker_loop, daemon=True,
                name="agentsec-session-worker",
            ).start()
            _worker_started = True


# --- драйвер прогона (выполняется в воркере) --------------------------------

def _run(
    session_id: str,
    *,
    task: str | None = None,
    resume: str | None = None,
    repo: str,
    interactive: bool = True,
) -> None:
    """Гоняет граф для сессии и переводит её статус по результату.

    Вызывается только из воркер-потока — мутация глобального `CONFIG`
    здесь безопасна, потому что прогон в каждый момент ровно один.
    """
    store = _get_store()
    # server_mode: _clarify/_gate ставят паузу через interrupt(), а не stdin.
    CONFIG.server_mode = True
    CONFIG.interactive = interactive
    CONFIG.analysis_root = Path(repo).expanduser().resolve()
    try:
        state = run_analysis(
            task=task,
            thread_id=session_id,
            resume=resume,
            checkpointer=make_checkpointer(CONFIG.session_db_path),
        )
        pause = interrupt_value(state)
        if pause is not None:
            # Граф встал на паузу — ждём ответ пользователя через resume.
            store.update_session(
                session_id,
                status=STATUS_AWAITING_INPUT,
                interrupt_type=pause.get("type"),
                interrupt_payload=pause,
            )
        else:
            # Граф дошёл до END — фиксируем вердикт и отчёт.
            store.update_session(
                session_id,
                status=STATUS_COMPLETED,
                interrupt_type=None,
                interrupt_payload=None,
                verdict=state.get("verdict"),
                report_md=state.get("report_md"),
            )
    except Exception as err:  # noqa: BLE001 — падение прогона ≠ падение сервиса
        store.update_session(
            session_id,
            status=STATUS_FAILED,
            error=f"{type(err).__name__}: {err}",
        )
        traceback.print_exc()


# --- публичный API фасада ----------------------------------------------------

def start_session(task: str, repo: str, *, interactive: bool = True) -> str:
    """Создаёт сессию, ставит скан в очередь и возвращает её id.

    Управление возвращается сразу: скан выполняется фоновым воркером.
    Клиент следит за прогрессом поллингом `get_session`.
    """
    task = (task or "").strip()
    if not task:
        raise ValueError("пустая задача — нечего анализировать")
    if not Path(repo).expanduser().is_dir():
        raise ValueError(f"каталог репозитория не найден: {repo}")

    session_id = uuid.uuid4().hex
    title = task[:60] + ("…" if len(task) > 60 else "")
    _get_store().create_session(SessionRecord(
        id=session_id, title=title, repo=repo, task=task,
        status=STATUS_RUNNING,
    ))
    _ensure_worker()
    _jobs.put((session_id, {"task": task, "repo": repo, "interactive": interactive}))
    return session_id


def resume_session(session_id: str, answer: str) -> None:
    """Передаёт ответ пользователя на паузу и возобновляет скан.

    Допустимо только для сессии в статусе `awaiting_input`; иначе —
    `ValueError` (бэкенд маппит его в HTTP 409).
    """
    store = _get_store()
    session = store.get_session(session_id)
    if session is None:
        raise ValueError(f"сессия не найдена: {session_id}")
    if session.status != STATUS_AWAITING_INPUT:
        raise ValueError(
            f"сессия {session_id} не ждёт ввода (статус: {session.status})")

    store.update_session(session_id, status=STATUS_RUNNING)
    _ensure_worker()
    # Возобновлять имеет смысл только интерактивный прогон (иначе пауз нет).
    _jobs.put((session_id, {"resume": answer, "repo": session.repo,
                            "interactive": True}))


def get_session(session_id: str) -> SessionRecord | None:
    """Полные данные сессии (для экрана детали/продолжения)."""
    return _get_store().get_session(session_id)


def list_sessions(limit: int = 50, offset: int = 0) -> list[SessionRecord]:
    """История сессий, новейшие первыми (для сайдбара во фронте)."""
    return _get_store().list_sessions(limit=limit, offset=offset)
