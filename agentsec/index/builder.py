"""Построение Repo Map: обход репозитория и извлечение символов.

Символы и рёбра вызовов: Python — через stdlib `ast` (точно, со
скоупами), прочие C-подобные языки — через регулярные выражения
(приблизительно, но без зависимостей). Sink-и и точки входа —
построчные regex из `patterns.py`. `index_file` индексирует один файл и
переиспользуется для инкрементальной переиндексации.
"""
from __future__ import annotations

import ast
import hashlib
import re
import subprocess
from pathlib import Path

from .languages import REGEX_SYMBOL_LANGS, language_of, role_of
from .model import CallEdge, EntryPoint, FileEntry, RepoMap, Sink, Symbol
from .patterns import scan_entry_points, scan_sinks

# Каталоги, которые не индексируем (мусор, зависимости, служебное).
_SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    "env", "dist", "build", ".idea", ".vscode", ".mypy_cache",
    ".pytest_cache", ".tox", ".agentsec", "site-packages", ".next",
}
# Файлы крупнее — индексируем как запись, но не парсим (защита от патологий).
_MAX_PARSE_BYTES = 1_500_000


# --- Python: точное извлечение через ast ------------------------------------

def _call_name(node: ast.AST) -> str | None:
    """Имя вызываемого: `foo` или `obj.method`."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _call_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return None


def _python_symbols(text: str, relpath: str) -> tuple[list[Symbol], list[CallEdge]]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return [], []
    symbols: list[Symbol] = []
    defs = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

    def walk(node: ast.AST, in_class: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, defs):
                if isinstance(child, ast.ClassDef):
                    kind = "class"
                else:
                    kind = "method" if in_class else "function"
                symbols.append(Symbol(
                    name=child.name, kind=kind, file=relpath,
                    line=child.lineno,
                    end_line=getattr(child, "end_lineno", child.lineno),
                ))
                walk(child, isinstance(child, ast.ClassDef))
            else:
                walk(child, in_class)

    walk(tree, False)
    # Вызов привязывается к самому вложенному символу, охватывающему строку.
    ordered = sorted(symbols, key=lambda s: s.end_line - s.line)
    calls: list[CallEdge] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            callee = _call_name(node.func)
            if not callee:
                continue
            line = node.lineno
            caller = next(
                (s.name for s in ordered if s.line <= line <= s.end_line),
                "<module>",
            )
            calls.append(CallEdge(caller=caller, callee=callee,
                                  file=relpath, line=line))
    return symbols, calls


# --- прочие языки: приблизительно через regex --------------------------------

_RX_CLASS = re.compile(r"\b(?:class|interface|struct|trait|enum)\s+"
                       r"([A-Za-z_]\w*)")
_RX_FUNC = re.compile(
    r"\bfunction\s+([A-Za-z_$][\w$]*)"                       # JS function decl
    r"|\bfunc\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)"             # Go func/method
    r"|\bdef\s+([A-Za-z_]\w*)"                               # Ruby/PHP-ish
    r"|\b([A-Za-z_$][\w$]*)\s*[:=]\s*(?:async\s+)?"          # JS arrow/expr
    r"(?:function\b|\([^)]*\)\s*=>)")
_RX_CALL = re.compile(r"\b([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)?)\s*\(")
_CALL_STOPWORDS = {"if", "for", "while", "switch", "catch", "function",
                   "return", "and", "or", "not"}


def _regex_symbols(text: str, relpath: str) -> tuple[list[Symbol], list[CallEdge]]:
    symbols: list[Symbol] = []
    calls: list[CallEdge] = []
    caller = "<module>"
    for lineno, line in enumerate(text.splitlines(), 1):
        cls = _RX_CLASS.search(line)
        if cls:
            symbols.append(Symbol(name=cls.group(1), kind="class",
                                  file=relpath, line=lineno, end_line=lineno))
        fn = _RX_FUNC.search(line)
        if fn:
            name = next((g for g in fn.groups() if g), None)
            if name:
                caller = name
                symbols.append(Symbol(name=name, kind="function",
                                      file=relpath, line=lineno,
                                      end_line=lineno))
        for m in _RX_CALL.finditer(line):
            callee = m.group(1)
            if callee.split(".")[0] not in _CALL_STOPWORDS:
                calls.append(CallEdge(caller=caller, callee=callee,
                                      file=relpath, line=lineno))
    # Грубая оценка границы символа — до начала следующего.
    ordered = sorted(symbols, key=lambda s: s.line)
    for cur, nxt in zip(ordered, ordered[1:]):
        cur.end_line = max(cur.line, nxt.line - 1)
    return symbols, calls


def _symbols_and_calls(
    language: str, text: str, relpath: str,
) -> tuple[list[Symbol], list[CallEdge]]:
    if language == "python":
        return _python_symbols(text, relpath)
    if language in REGEX_SYMBOL_LANGS:
        return _regex_symbols(text, relpath)
    return [], []


# --- обход репозитория -------------------------------------------------------

def _read(path: Path) -> tuple[str, bytes] | None:
    """Читает файл как текст; None — бинарный/нечитаемый."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data[:8192]:  # грубая отсечка бинарей
        return None
    return data.decode("utf-8", "replace"), data


def index_file(root: Path, relpath: str) -> tuple[
    FileEntry, list[Symbol], list[CallEdge], list[EntryPoint], list[Sink]
] | None:
    """Индексирует один файл. None — файл пропущен (бинарь/нечитаемый)."""
    payload = _read(root / relpath)
    if payload is None:
        return None
    text, data = payload
    language = language_of(relpath)
    entry = FileEntry(
        path=relpath,
        language=language,
        role=role_of(relpath),
        loc=sum(1 for ln in text.splitlines() if ln.strip()),
        size=len(data),
        content_hash=hashlib.sha1(data).hexdigest(),
    )
    symbols: list[Symbol] = []
    calls: list[CallEdge] = []
    if language != "unknown" and len(data) <= _MAX_PARSE_BYTES:
        symbols, calls = _symbols_and_calls(language, text, relpath)
    return entry, symbols, calls, scan_entry_points(text, relpath), \
        scan_sinks(text, relpath)


def _iter_files(root: Path):
    """Обходит репозиторий, отдавая относительные пути (без мусорных каталогов)."""
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in _SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        yield path.relative_to(root).as_posix()


def git_commit(root: Path) -> str:
    """Хеш текущего git-коммита репозитория (пусто, если не git/нет git)."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
            text=True, timeout=10, check=False,
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def build_repo_map(root: Path) -> RepoMap:
    """Строит полный Repo Map репозитория с нуля."""
    repo = RepoMap(root=str(root), commit=git_commit(root))
    for relpath in _iter_files(root):
        result = index_file(root, relpath)
        if result is None:
            continue
        entry, symbols, calls, entry_points, sinks = result
        repo.files.append(entry)
        repo.symbols.extend(symbols)
        repo.calls.extend(calls)
        repo.entry_points.extend(entry_points)
        repo.sinks.extend(sinks)
    return repo
