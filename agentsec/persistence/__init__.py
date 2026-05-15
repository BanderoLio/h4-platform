"""Слой персистентности: история сессий анализа и чекпоинтер графа.

`store` — метаданные сессий (список истории, статус, вердикт, отчёт).
`checkpointer` — фабрика SQLite-чекпоинтера LangGraph (состояние графа
для паузы на interrupt() и возобновления). Оба пишут в один файл
`CONFIG.session_db_path`, но в разные таблицы.
"""
from __future__ import annotations

from .checkpointer import make_checkpointer
from .store import (
    SESSION_STATUSES,
    STATUS_AWAITING_INPUT,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_RUNNING,
    SessionRecord,
    SessionStore,
    SqliteSessionStore,
)

__all__ = [
    "make_checkpointer",
    "SessionRecord",
    "SessionStore",
    "SqliteSessionStore",
    "SESSION_STATUSES",
    "STATUS_RUNNING",
    "STATUS_AWAITING_INPUT",
    "STATUS_COMPLETED",
    "STATUS_FAILED",
]
