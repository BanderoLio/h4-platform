"""Языки и роли файлов.

Извлечение символов: Python — через stdlib `ast` (точно), остальные
языки — через регулярные выражения (`builder.py`). Зависимостей нет.
"""
from __future__ import annotations

from pathlib import PurePosixPath

from .model import (
    ROLE_CONFIG,
    ROLE_DOCS,
    ROLE_GENERATED,
    ROLE_OTHER,
    ROLE_SOURCE,
    ROLE_TEST,
    ROLE_VENDOR,
)

# Расширение → язык tree-sitter.
EXT_TO_LANG: dict[str, str] = {
    ".py": "python",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
    ".ts": "typescript", ".tsx": "tsx",
    ".go": "go",
    ".java": "java",
    ".rb": "ruby",
    ".php": "php",
    ".c": "c", ".h": "c",
    ".cc": "cpp", ".cpp": "cpp", ".hpp": "cpp",
    ".rs": "rust",
    ".cs": "c_sharp",
}

# Конфигурационные/манифест-файлы по имени.
_CONFIG_NAMES = {
    "dockerfile", "makefile", "requirements.txt", "package.json",
    "package-lock.json", "go.mod", "go.sum", "setup.py", "setup.cfg",
    "pyproject.toml", "cargo.toml", "pom.xml", "build.gradle", ".env",
}
_CONFIG_EXTS = {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".xml", ".env"}
_DOC_EXTS = {".md", ".rst", ".txt", ".adoc"}

# Языки, для которых символы извлекаются регулярками (C-семейство синтаксиса).
REGEX_SYMBOL_LANGS = {"javascript", "typescript", "tsx", "go", "java",
                      "php", "c_sharp", "rust", "c", "cpp"}


def language_of(path: str) -> str:
    """Определяет язык файла по расширению (или 'unknown')."""
    suffix = PurePosixPath(path).suffix.lower()
    return EXT_TO_LANG.get(suffix, "unknown")


def role_of(path: str) -> str:
    """Классифицирует роль файла: source / test / config / docs / …"""
    p = PurePosixPath(path)
    parts = {part.lower() for part in p.parts}
    name = p.name.lower()
    suffix = p.suffix.lower()

    if {"node_modules", "vendor", "third_party", "site-packages"} & parts:
        return ROLE_VENDOR
    if name.endswith((".min.js", ".min.css")) or "generated" in parts \
            or "__generated__" in parts:
        return ROLE_GENERATED
    if ({"test", "tests", "__tests__", "spec"} & parts
            or name.startswith("test_")
            or name == "conftest.py"
            or any(s in name for s in ("_test.", ".test.", ".spec."))):
        return ROLE_TEST
    if suffix in _DOC_EXTS:
        return ROLE_DOCS
    if name in _CONFIG_NAMES or suffix in _CONFIG_EXTS:
        return ROLE_CONFIG
    if language_of(path) != "unknown":
        return ROLE_SOURCE
    return ROLE_OTHER
