"""Хранилище метаданных сессий анализа.

Сессия — один прогон оркестратора с устойчивым `id` (он же `thread_id`
LangGraph). Таблица `sessions` отвечает за «историю» во фронте: список
прошлых сканов, их статус, вердикт и итоговый отчёт. Само состояние
графа хранит чекпоинтер LangGraph (см. `checkpointer.py`) — в том же
SQLite-файле, в своих таблицах.

`SessionStore` — абстракция: сегодня SQLite, завтра можно подменить на
`PostgresSessionStore` с той же сигнатурой, не трогая оркестратор.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# --- статусы жизненного цикла сессии ----------------------------------------
STATUS_RUNNING = "running"              # граф выполняется
STATUS_AWAITING_INPUT = "awaiting_input"  # пауза на interrupt(), ждём ответ
STATUS_COMPLETED = "completed"          # граф дошёл до END
STATUS_FAILED = "failed"                # прогон упал с исключением
SESSION_STATUSES = (
    STATUS_RUNNING,
    STATUS_AWAITING_INPUT,
    STATUS_COMPLETED,
    STATUS_FAILED,
)


def _now() -> str:
    """Текущее время в ISO-8601 (UTC)."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SessionRecord:
    """Строка таблицы `sessions` — зеркало одной сессии анализа."""

    id: str                                  # uuid4 hex, он же thread_id
    title: str                               # краткий заголовок (из задачи)
    repo: str                                # путь к анализируемому репо
    task: str                                # исходная задача
    status: str = STATUS_RUNNING
    interrupt_type: str | None = None        # 'clarify' / 'gate' при паузе
    interrupt_payload: dict[str, Any] | None = None  # что показать пользователю
    verdict: dict[str, Any] | None = None    # JSON-сводка quality gate
    report_md: str | None = None             # итоговый markdown-отчёт
    findings: list[dict[str, Any]] | None = None  # структурные находки (JSON)
    coverage: list[dict[str, Any]] | None = None  # трекинг покрытия (JSON)
    error: str | None = None                 # текст исключения при failed
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        """Сериализуемое представление (для API-ответов)."""
        return asdict(self)


# JSON-поля: в БД хранятся как TEXT, в SessionRecord — как dict/list.
_JSON_FIELDS = ("interrupt_payload", "verdict", "findings", "coverage")
_COLUMNS = (
    "id", "title", "repo", "task", "status", "interrupt_type",
    "interrupt_payload", "verdict", "report_md", "findings", "coverage",
    "error", "created_at", "updated_at",
)


class SessionStore(ABC):
    """Абстракция хранилища сессий. Реализации: SQLite, в будущем Postgres."""

    @abstractmethod
    def create_session(self, session: SessionRecord) -> None:
        """Сохраняет новую сессию."""

    @abstractmethod
    def get_session(self, session_id: str) -> SessionRecord | None:
        """Возвращает сессию по id или None."""

    @abstractmethod
    def list_sessions(self, limit: int = 50, offset: int = 0) -> list[SessionRecord]:
        """Список сессий, новейшие первыми (для истории во фронте)."""

    @abstractmethod
    def update_session(self, session_id: str, **fields: Any) -> None:
        """Точечно обновляет поля сессии; updated_at ставится автоматически."""


class SqliteSessionStore(SessionStore):
    """Реализация `SessionStore` на stdlib sqlite3.

    Одно соединение под `threading.Lock`: сканы идут в фоновом потоке,
    а API-запросы — в потоках веб-сервера. WAL-режим даёт читать историю,
    пока пишется активный скан.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._path = str(db_path)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id                TEXT PRIMARY KEY,
                    title             TEXT NOT NULL,
                    repo              TEXT NOT NULL,
                    task              TEXT NOT NULL,
                    status            TEXT NOT NULL,
                    interrupt_type    TEXT,
                    interrupt_payload TEXT,
                    verdict           TEXT,
                    report_md         TEXT,
                    findings          TEXT,
                    coverage          TEXT,
                    error             TEXT,
                    created_at        TEXT NOT NULL,
                    updated_at        TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_created "
                "ON sessions (created_at DESC)"
            )
            self._migrate_columns()
            self._conn.commit()

    def _migrate_columns(self) -> None:
        """Догоняет схему БД, созданной прежней версией: добавляет колонки,
        появившиеся позже (`findings`, `coverage`). SQLite ALTER TABLE ADD
        COLUMN дёшев и безопасен — старые строки получают NULL."""
        existing = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(sessions)").fetchall()
        }
        for column in ("findings", "coverage"):
            if column not in existing:
                self._conn.execute(
                    f"ALTER TABLE sessions ADD COLUMN {column} TEXT"
                )

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> SessionRecord:
        data = dict(row)
        for field_name in _JSON_FIELDS:
            raw = data.get(field_name)
            data[field_name] = json.loads(raw) if raw else None
        return SessionRecord(**data)

    @staticmethod
    def _encode(field_name: str, value: Any) -> Any:
        """Готовит значение поля к записи в SQLite."""
        if field_name in _JSON_FIELDS and value is not None:
            return json.dumps(value, ensure_ascii=False, default=str)
        return value

    def create_session(self, session: SessionRecord) -> None:
        values = [self._encode(c, getattr(session, c)) for c in _COLUMNS]
        placeholders = ", ".join("?" for _ in _COLUMNS)
        with self._lock:
            self._conn.execute(
                f"INSERT INTO sessions ({', '.join(_COLUMNS)}) "
                f"VALUES ({placeholders})",
                values,
            )
            self._conn.commit()

    def get_session(self, session_id: str) -> SessionRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        return self._row_to_record(row) if row else None

    def list_sessions(self, limit: int = 50, offset: int = 0) -> list[SessionRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM sessions ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def update_session(self, session_id: str, **fields: Any) -> None:
        if not fields:
            return
        unknown = set(fields) - set(_COLUMNS)
        if unknown:
            raise ValueError(f"неизвестные поля сессии: {sorted(unknown)}")
        fields["updated_at"] = _now()
        assignments = ", ".join(f"{k} = ?" for k in fields)
        values = [self._encode(k, v) for k, v in fields.items()]
        values.append(session_id)
        with self._lock:
            self._conn.execute(
                f"UPDATE sessions SET {assignments} WHERE id = ?", values
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
