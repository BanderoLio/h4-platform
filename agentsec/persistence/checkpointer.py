"""Фабрика SQLite-чекпоинтера LangGraph.

Чекпоинтер хранит состояние графа (`AnalysisState`) по `thread_id`:
именно он даёт паузу на `interrupt()` и возобновление с того же места.
Берём синхронный `SqliteSaver` — граф вызывается синхронно
(`graph.invoke()`) в фоновом потоке, async-saver не нужен.

Чекпоинтер создаётся один раз на процесс (синглтон по пути файла) и
держится открытым: он переживает отдельные прогоны графа.
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver

_lock = threading.Lock()
_cache: dict[str, SqliteSaver] = {}

# Состояние графа содержит наши dataclass-ы (Finding, Coverage). По
# умолчанию msgpack-сериализатор LangGraph их не знает и в будущих
# версиях откажется десериализовать. Явно разрешаем модуль схемы.
_SERDE = JsonPlusSerializer(
    allowed_msgpack_modules=[
        ("agentsec.schema", "Finding"),
        ("agentsec.schema", "Coverage"),
    ]
)


def make_checkpointer(db_path: str | Path) -> SqliteSaver:
    """Возвращает (создавая при первом обращении) `SqliteSaver` для файла.

    Соединение — `check_same_thread=False`: чекпоинтером пользуются и
    фоновый воркер, и веб-потоки. WAL-режим разрешает читать историю,
    пока идёт активный скан.
    """
    key = str(Path(db_path))
    with _lock:
        saver = _cache.get(key)
        if saver is None:
            conn = sqlite3.connect(key, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            saver = SqliteSaver(conn, serde=_SERDE)
            saver.setup()  # создаёт таблицы чекпоинтера, если их ещё нет
            _cache[key] = saver
        return saver
