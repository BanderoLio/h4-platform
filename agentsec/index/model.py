"""Структуры данных Repo Map — контекста кодовой базы.

Repo Map — детерминированно выведенный из кода индекс: инвентарь файлов,
символы, рёбра вызовов, точки входа (attack surface) и опасные операции
(sinks). Хранится в SQLite (`store.py`), запрашивается агентами
(`query.py`) — так «размер репозитория» развязан с «размером контекста».
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# --- роли файлов ------------------------------------------------------------
ROLE_SOURCE = "source"
ROLE_TEST = "test"
ROLE_CONFIG = "config"
ROLE_DOCS = "docs"
ROLE_VENDOR = "vendor"
ROLE_GENERATED = "generated"
ROLE_OTHER = "other"

# --- виды точек входа (attack surface) --------------------------------------
EP_HTTP_ROUTE = "http_route"
EP_CLI = "cli"
EP_HANDLER = "handler"          # очереди, события, вебхуки
EP_MAIN = "main"                # точка запуска процесса

# --- виды sink-ов (опасные операции) ----------------------------------------
SINK_SQL = "sql"
SINK_COMMAND = "command"
SINK_DESERIALIZE = "deserialization"
SINK_FILE = "file"
SINK_EVAL = "eval"
SINK_CRYPTO = "crypto"
SINK_SSRF = "ssrf"
SINK_SECRET = "secret"          # захардкоженный секрет/ключ/пароль


@dataclass
class FileEntry:
    """Один файл репозитория в инвентаре."""

    path: str                # путь относительно корня репозитория
    language: str            # python / javascript / ... / unknown
    role: str = ROLE_OTHER
    loc: int = 0             # непустых строк кода
    size: int = 0            # размер в байтах
    content_hash: str = ""   # sha1 содержимого — для инкрементальной переиндексации

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Symbol:
    """Определение функции/класса/метода."""

    name: str
    kind: str                # function / class / method
    file: str
    line: int
    end_line: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CallEdge:
    """Ребро графа вызовов: caller вызывает callee (по имени, без резолва)."""

    caller: str              # имя символа или '<module>'
    callee: str
    file: str
    line: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EntryPoint:
    """Точка входа — элемент attack surface."""

    kind: str                # см. EP_* выше
    name: str                # путь роута / имя команды / имя обработчика
    file: str
    line: int
    detail: str = ""         # HTTP-метод, фреймворк и т.п.

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Sink:
    """Опасная операция — потенциальный sink уязвимости."""

    kind: str                # см. SINK_* выше
    file: str
    line: int
    snippet: str = ""        # строка кода (обрезанная)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RepoMap:
    """Полный индекс репозитория — результат построения (`builder.py`)."""

    root: str
    commit: str = ""
    files: list[FileEntry] = field(default_factory=list)
    symbols: list[Symbol] = field(default_factory=list)
    calls: list[CallEdge] = field(default_factory=list)
    entry_points: list[EntryPoint] = field(default_factory=list)
    sinks: list[Sink] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        """Краткая сводка для recon/отчёта (без выгрузки всех таблиц)."""
        languages: dict[str, int] = {}
        for f in self.files:
            languages[f.language] = languages.get(f.language, 0) + 1
        sink_kinds: dict[str, int] = {}
        for s in self.sinks:
            sink_kinds[s.kind] = sink_kinds.get(s.kind, 0) + 1
        return {
            "root": self.root,
            "commit": self.commit,
            "files": len(self.files),
            "loc": sum(f.loc for f in self.files),
            "languages": dict(sorted(languages.items(),
                                     key=lambda kv: -kv[1])),
            "symbols": len(self.symbols),
            "call_edges": len(self.calls),
            "entry_points": len(self.entry_points),
            "sinks": len(self.sinks),
            "sink_kinds": sink_kinds,
        }
