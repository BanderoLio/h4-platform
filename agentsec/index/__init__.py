"""Repo Map — детерминированный индекс кодовой базы (контекст по репо).

`builder` строит индекс (символы, вызовы, точки входа, sink-и),
`store` хранит его в SQLite инкрементально, `query` отдаёт точечные
срезы. Агенты обращаются к индексу через `tools/repomap.py`.
"""
from __future__ import annotations

from .builder import build_repo_map
from .model import CallEdge, EntryPoint, FileEntry, RepoMap, Sink, Symbol
from .store import IndexStore, index_db_path, index_repo

__all__ = [
    "build_repo_map",
    "index_repo",
    "IndexStore",
    "index_db_path",
    "RepoMap",
    "FileEntry",
    "Symbol",
    "CallEdge",
    "EntryPoint",
    "Sink",
]
