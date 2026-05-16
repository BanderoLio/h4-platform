"""Запросы к Repo Map — точечные срезы по индексу без выгрузки всего.

Каждая функция отдаёт небольшой список dict-ов: именно это потом
попадает в контекст агента (`tools/repomap.py`), а не весь индекс.
"""
from __future__ import annotations

from typing import Any

from .store import IndexStore


def _rows(store: IndexStore, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in store.query(sql, params)]


def summary(store: IndexStore) -> dict[str, Any]:
    """Сводка по репозиторию: файлы, языки, символы, attack surface."""
    files = _rows(store, "SELECT language, role, loc FROM files")
    languages: dict[str, int] = {}
    roles: dict[str, int] = {}
    for f in files:
        languages[f["language"]] = languages.get(f["language"], 0) + 1
        roles[f["role"]] = roles.get(f["role"], 0) + 1
    sink_kinds = {r["kind"]: r["n"] for r in _rows(
        store, "SELECT kind, COUNT(*) n FROM sinks GROUP BY kind")}
    return {
        "root": store.get_meta("root"),
        "commit": store.get_meta("commit"),
        "files": len(files),
        "loc": sum(f["loc"] or 0 for f in files),
        "languages": dict(sorted(languages.items(), key=lambda kv: -kv[1])),
        "roles": roles,
        "symbols": store.query("SELECT COUNT(*) n FROM symbols")[0]["n"],
        "entry_points": store.query(
            "SELECT COUNT(*) n FROM entry_points")[0]["n"],
        "sinks": store.query("SELECT COUNT(*) n FROM sinks")[0]["n"],
        "sink_kinds": sink_kinds,
    }


def entry_points(store: IndexStore, kind: str | None = None) -> list[dict[str, Any]]:
    """Точки входа (attack surface). Опционально фильтр по виду."""
    if kind:
        return _rows(store, "SELECT * FROM entry_points WHERE kind = ? "
                            "ORDER BY file, line", (kind,))
    return _rows(store, "SELECT * FROM entry_points ORDER BY file, line")


def sinks(store: IndexStore, kind: str | None = None,
          file: str | None = None) -> list[dict[str, Any]]:
    """Опасные операции. Фильтры по виду sink-а и/или файлу."""
    clauses, params = [], []
    if kind:
        clauses.append("kind = ?")
        params.append(kind)
    if file:
        clauses.append("file = ?")
        params.append(file)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return _rows(store, f"SELECT * FROM sinks{where} ORDER BY file, line",
                 tuple(params))


def who_calls(store: IndexStore, name: str) -> list[dict[str, Any]]:
    """Места вызова символа (callee == name или *.name)."""
    return _rows(store, "SELECT * FROM calls WHERE callee = ? OR callee LIKE ? "
                        "ORDER BY file, line", (name, f"%.{name}"))


def callees_of(store: IndexStore, caller: str) -> list[dict[str, Any]]:
    """Что вызывает заданный символ."""
    return _rows(store, "SELECT * FROM calls WHERE caller = ? ORDER BY file, line",
                 (caller,))


def symbol_lookup(store: IndexStore, name: str,
                  exact: bool = False) -> list[dict[str, Any]]:
    """Определения символа по имени (точно или по подстроке)."""
    if exact:
        return _rows(store, "SELECT * FROM symbols WHERE name = ? "
                            "ORDER BY file, line", (name,))
    return _rows(store, "SELECT * FROM symbols WHERE name LIKE ? "
                        "ORDER BY file, line LIMIT 100", (f"%{name}%",))


def file_outline(store: IndexStore, path: str) -> list[dict[str, Any]]:
    """Карта символов файла (для навигации без чтения целиком)."""
    return _rows(store, "SELECT name, kind, line, end_line FROM symbols "
                        "WHERE file = ? ORDER BY line", (path,))


def find_files(store: IndexStore, role: str | None = None,
               language: str | None = None) -> list[dict[str, Any]]:
    """Файлы инвентаря с фильтрами по роли и языку."""
    clauses, params = [], []
    if role:
        clauses.append("role = ?")
        params.append(role)
    if language:
        clauses.append("language = ?")
        params.append(language)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return _rows(store, f"SELECT * FROM files{where} ORDER BY path",
                 tuple(params))
