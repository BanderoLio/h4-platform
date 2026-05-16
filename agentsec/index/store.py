"""SQLite-хранилище Repo Map + инкрементальная переиндексация.

Индекс лежит в `.agentsec/index.db` внутри анализируемого репозитория.
Сам индекс в контекстное окно не попадает — агенты получают только
результаты запросов (`query.py`). Инкрементальность: на повторном
прогоне переиндексируются лишь файлы с изменившимся content_hash.
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from .builder import _iter_files, git_commit, index_file
from .model import CallEdge, EntryPoint, FileEntry, RepoMap, Sink, Symbol

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS files (
    path TEXT PRIMARY KEY, language TEXT, role TEXT,
    loc INTEGER, size INTEGER, content_hash TEXT);
CREATE TABLE IF NOT EXISTS symbols (
    name TEXT, kind TEXT, file TEXT, line INTEGER, end_line INTEGER);
CREATE TABLE IF NOT EXISTS calls (
    caller TEXT, callee TEXT, file TEXT, line INTEGER);
CREATE TABLE IF NOT EXISTS entry_points (
    kind TEXT, name TEXT, file TEXT, line INTEGER, detail TEXT);
CREATE TABLE IF NOT EXISTS sinks (
    kind TEXT, file TEXT, line INTEGER, snippet TEXT);
CREATE TABLE IF NOT EXISTS scanner_findings (
    tool TEXT, rule TEXT, vuln_class TEXT, file TEXT,
    line INTEGER, severity TEXT, message TEXT);
CREATE INDEX IF NOT EXISTS idx_sym_name ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_sym_file ON symbols(file);
CREATE INDEX IF NOT EXISTS idx_calls_callee ON calls(callee);
CREATE INDEX IF NOT EXISTS idx_calls_caller ON calls(caller);
CREATE INDEX IF NOT EXISTS idx_sinks_kind ON sinks(kind);
CREATE INDEX IF NOT EXISTS idx_scan_class ON scanner_findings(vuln_class);
"""


def index_db_path(repo_root: Path) -> Path:
    """Путь к файлу индекса для репозитория."""
    return Path(repo_root) / ".agentsec" / "index.db"


class IndexStore:
    """SQLite-хранилище Repo Map. Одно соединение под `threading.Lock`."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # --- инкрементальная запись ---------------------------------------------

    def file_hashes(self) -> dict[str, str]:
        """`{path: content_hash}` уже проиндексированных файлов."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT path, content_hash FROM files").fetchall()
        return {r["path"]: r["content_hash"] for r in rows}

    def replace_file(self, entry: FileEntry, symbols: list[Symbol],
                     calls: list[CallEdge], entry_points: list[EntryPoint],
                     sinks: list[Sink]) -> None:
        """Перезаписывает все данные одного файла (upsert + чистка старых строк)."""
        with self._lock:
            c = self._conn
            for table in ("symbols", "calls", "entry_points", "sinks"):
                c.execute(f"DELETE FROM {table} WHERE file = ?", (entry.path,))
            c.execute("INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?)",
                      (entry.path, entry.language, entry.role, entry.loc,
                       entry.size, entry.content_hash))
            c.executemany(
                "INSERT INTO symbols VALUES (?,?,?,?,?)",
                [(s.name, s.kind, s.file, s.line, s.end_line) for s in symbols])
            c.executemany(
                "INSERT INTO calls VALUES (?,?,?,?)",
                [(e.caller, e.callee, e.file, e.line) for e in calls])
            c.executemany(
                "INSERT INTO entry_points VALUES (?,?,?,?,?)",
                [(e.kind, e.name, e.file, e.line, e.detail)
                 for e in entry_points])
            c.executemany(
                "INSERT INTO sinks VALUES (?,?,?,?)",
                [(s.kind, s.file, s.line, s.snippet) for s in sinks])
            c.commit()

    def delete_file(self, path: str) -> None:
        """Удаляет из индекса все данные файла (файл исчез из репозитория)."""
        with self._lock:
            for table in ("files", "symbols", "calls", "entry_points", "sinks"):
                self._conn.execute(f"DELETE FROM {table} WHERE "
                                   f"{'path' if table == 'files' else 'file'} = ?",
                                   (path,))
            self._conn.commit()

    def set_meta(self, **values: str) -> None:
        with self._lock:
            self._conn.executemany(
                "INSERT OR REPLACE INTO meta VALUES (?,?)",
                [(k, str(v)) for k, v in values.items()])
            self._conn.commit()

    def get_meta(self, key: str, default: str = "") -> str:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    # --- находки сканеров ----------------------------------------------------

    def candidate_files(self) -> list[str]:
        """Файлы, где индекс нашёл sink-и или точки входа — поверхность для
        прицельного прогона сканеров."""
        rows = self.query(
            "SELECT file FROM sinks UNION SELECT file FROM entry_points")
        return sorted(r["file"] for r in rows)

    def replace_scanner_findings(self, rows: list[dict]) -> None:
        """Полностью перезаписывает таблицу находок сканеров."""
        with self._lock:
            self._conn.execute("DELETE FROM scanner_findings")
            self._conn.executemany(
                "INSERT INTO scanner_findings VALUES (?,?,?,?,?,?,?)",
                [(r.get("tool", ""), r.get("rule", ""),
                  r.get("vuln_class", ""), r.get("file", ""),
                  r.get("line", 0), r.get("severity", ""),
                  r.get("message", "")) for r in rows])
            self._conn.commit()

    # --- чтение --------------------------------------------------------------

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        """Произвольный SELECT по индексу (используется `query.py`)."""
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def load(self) -> RepoMap:
        """Поднимает весь Repo Map обратно в память."""
        repo = RepoMap(root=self.get_meta("root"),
                       commit=self.get_meta("commit"))
        for r in self.query("SELECT * FROM files"):
            repo.files.append(FileEntry(**dict(r)))
        for r in self.query("SELECT * FROM symbols"):
            repo.symbols.append(Symbol(**dict(r)))
        for r in self.query("SELECT * FROM calls"):
            repo.calls.append(CallEdge(**dict(r)))
        for r in self.query("SELECT * FROM entry_points"):
            repo.entry_points.append(EntryPoint(**dict(r)))
        for r in self.query("SELECT * FROM sinks"):
            repo.sinks.append(Sink(**dict(r)))
        return repo

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def index_repo(repo_root: str | Path, *, db_path: str | Path | None = None,
               force: bool = False) -> tuple[IndexStore, dict[str, int]]:
    """Строит/обновляет индекс репозитория инкрементально.

    Возвращает открытый `IndexStore` и статистику `{indexed, reused,
    removed}`. Файлы с неизменившимся content_hash не переиндексируются.
    """
    root = Path(repo_root).resolve()
    store = IndexStore(db_path or index_db_path(root))
    cached = {} if force else store.file_hashes()
    seen: set[str] = set()
    indexed = reused = 0

    for relpath in _iter_files(root):
        result = index_file(root, relpath)
        if result is None:
            continue
        entry = result[0]
        seen.add(relpath)
        if cached.get(relpath) == entry.content_hash:
            reused += 1
            continue
        store.replace_file(*result)
        indexed += 1

    removed = 0
    for stale in set(cached) - seen:
        store.delete_file(stale)
        removed += 1

    store.set_meta(root=str(root), commit=git_commit(root))
    return store, {"indexed": indexed, "reused": reused, "removed": removed}
