"""Файловые инструменты агентов.

Все пути резолвятся строго внутри CONFIG.analysis_root — выход за корень
анализа запрещён. read_file обрезает вывод, write/edit спрашивают
подтверждение у пользователя.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from langchain_core.tools import tool

from ..config import CONFIG

# Каталоги, которые нет смысла анализировать (мусор/зависимости/служебное).
_SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env",
    "dist", "build", ".idea", ".mypy_cache", ".pytest_cache", ".tox",
    ".agentsec",
}


def _resolve(path: str) -> Path:
    """Резолвит path внутри корня анализа, защищая от path traversal наружу."""
    root = CONFIG.analysis_root.resolve()
    raw = Path(path)
    candidate = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"Путь '{path}' вне корня анализа {root}")
    return candidate


def _confirm(action: str) -> bool:
    """Запрашивает у пользователя разрешение на изменяющую операцию."""
    if CONFIG.auto_approve_writes:
        return True
    print(f"\n[ЗАПРОС РАЗРЕШЕНИЯ] Агент хочет: {action}")
    answer = input("Разрешить? [y/N]: ").strip().lower()
    return answer in {"y", "yes", "д", "да"}


@tool
def read_file(path: str, offset: int = 0, limit: int = 0) -> str:
    """Прочитать текстовый файл по пути относительно корня анализа.

    Возвращает содержимое с нумерацией строк (формат 'N<TAB>текст').
    offset — номер первой строки (1-based), limit — сколько строк читать.
    Для больших файлов читай нужное окно (offset/limit), а не файл
    целиком — это экономит контекст. Без offset/limit читается начало
    файла до символьного лимита.
    """
    try:
        p = _resolve(path)
    except ValueError as e:
        return f"ОШИБКА: {e}"
    if not p.is_file():
        return f"ОШИБКА: файл не найден: {path}"
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001 — инструмент не должен падать
        return f"ОШИБКА чтения {path}: {e}"

    lines = text.splitlines()
    total = len(lines)
    char_limit = CONFIG.read_file_max_chars

    if offset or limit:
        start = max(0, offset - 1)
        count = limit if limit > 0 else total
        window = lines[start:start + count]
        numbered = "\n".join(f"{start + i + 1}\t{ln}"
                             for i, ln in enumerate(window))
        if len(numbered) > char_limit:
            numbered = numbered[:char_limit] + "\n... [обрезано по символам]"
        shown_to = start + len(window)
        header = f"[строки {start + 1}-{shown_to} из {total}]"
        return f"{header}\n{numbered}" if window else f"{header}\n(пусто)"

    truncated = len(text) > char_limit
    if truncated:
        text = text[:char_limit]
    numbered = "\n".join(f"{i}\t{ln}" for i, ln in enumerate(text.splitlines(), 1))
    if truncated:
        numbered += (f"\n... [обрезано: показан лимит {char_limit} символов; "
                     f"всего строк {total} — дочитай через offset/limit]")
    return numbered or "(пустой файл)"


@tool
def write_file(path: str, content: str) -> str:
    """Создать или перезаписать файл. Требует подтверждения пользователя.

    Предназначено для написания тестов и PoC-эксплойтов. Исходный код
    анализируемой цели править не нужно.
    """
    try:
        p = _resolve(path)
    except ValueError as e:
        return f"ОШИБКА: {e}"
    if not _confirm(f"записать файл {path} ({len(content)} символов)"):
        return "ОТКЛОНЕНО пользователем."
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"OK: записан {path}"


@tool
def edit_file(path: str, old: str, new: str) -> str:
    """Заменить точное вхождение old на new в файле. Требует подтверждения.

    old должен быть уникальным фрагментом РЕАЛЬНОГО содержимого файла
    (без номеров строк, которые добавляет read_file).
    """
    try:
        p = _resolve(path)
    except ValueError as e:
        return f"ОШИБКА: {e}"
    if not p.is_file():
        return f"ОШИБКА: файл не найден: {path}"
    text = p.read_text(encoding="utf-8", errors="replace")
    count = text.count(old)
    if count == 0:
        return "ОШИБКА: фрагмент old не найден в файле."
    if count > 1:
        return "ОШИБКА: фрагмент old не уникален — добавьте контекста."
    if not _confirm(f"отредактировать файл {path}"):
        return "ОТКЛОНЕНО пользователем."
    p.write_text(text.replace(old, new, 1), encoding="utf-8")
    return f"OK: отредактирован {path}"


@tool
def list_dir(path: str = ".") -> str:
    """Список файлов и подкаталогов в каталоге относительно корня анализа."""
    try:
        p = _resolve(path)
    except ValueError as e:
        return f"ОШИБКА: {e}"
    if not p.is_dir():
        return f"ОШИБКА: каталог не найден: {path}"
    entries = []
    for child in sorted(p.iterdir()):
        if child.name in _SKIP_DIRS:
            continue
        prefix = "[dir] " if child.is_dir() else "      "
        entries.append(prefix + child.name)
    return "\n".join(entries) or "(пусто)"


@tool
def glob_files(pattern: str) -> str:
    """Найти файлы по glob-шаблону (например '**/*.py') от корня анализа."""
    root = CONFIG.analysis_root.resolve()
    matches = []
    for p in root.glob(pattern):
        if not p.is_file():
            continue
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        matches.append(str(p.relative_to(root)))
    matches.sort()
    if not matches:
        return "(ничего не найдено)"
    if len(matches) > 200:
        return "\n".join(matches[:200]) + f"\n... [ещё {len(matches) - 200} файлов]"
    return "\n".join(matches)


@tool
def grep(pattern: str, path: str = ".", glob: str = "**/*") -> str:
    """Поиск по регулярному выражению в файлах.

    path — подкаталог поиска, glob — фильтр файлов внутри него.
    Результат — строки в формате 'файл:номер:текст'.
    """
    try:
        rx = re.compile(pattern)
    except re.error as e:
        return f"ОШИБКА регулярного выражения: {e}"
    try:
        base = _resolve(path)
    except ValueError as e:
        return f"ОШИБКА: {e}"

    root = CONFIG.analysis_root.resolve()
    files = [base] if base.is_file() else base.glob(glob)
    results: list[str] = []
    for f in files:
        if not f.is_file() or any(part in _SKIP_DIRS for part in f.parts):
            continue
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 — бинарь/недоступный файл просто пропускаем
            continue
        for n, line in enumerate(content.splitlines(), 1):
            if rx.search(line):
                rel = f.relative_to(root)
                results.append(f"{rel}:{n}:{line.strip()[:200]}")
                if len(results) >= 300:
                    return "\n".join(results) + "\n... [достигнут лимит 300 совпадений]"
    return "\n".join(results) or "(совпадений нет)"
