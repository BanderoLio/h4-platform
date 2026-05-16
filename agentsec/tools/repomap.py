"""Инструменты запросов к Repo Map для агентов.

Repo Map — детерминированный индекс кодовой базы (см. `agentsec/index/`).
Эти инструменты дают агенту точечные срезы — точки входа, sink-и,
символы, граф вызовов — вместо слепого обхода репозитория через grep.
Так «размер репозитория» развязан с «размером контекста».
"""
from __future__ import annotations

from langchain_core.tools import tool

from ..config import CONFIG
from ..index import query as Q
from ..index.store import IndexStore, index_db_path

_MAX_ROWS = 80  # верхняя граница строк в одном ответе — защита контекста


def _open() -> IndexStore | None:
    """Открывает индекс анализируемого репозитория или None, если не построен."""
    path = index_db_path(CONFIG.analysis_root)
    return IndexStore(path) if path.exists() else None


def _fmt(rows: list[dict], line: str, *, empty: str) -> str:
    """Рендерит список строк под лимит, с явной пометкой обрезки."""
    if not rows:
        return empty
    shown = rows[:_MAX_ROWS]
    body = "\n".join(line.format(**r) for r in shown)
    if len(rows) > _MAX_ROWS:
        body += f"\n... [показано {_MAX_ROWS} из {len(rows)}; сузь запрос]"
    return body


_NO_INDEX = ("Repo Map не построен. Индекс строится узлом графа `index` "
             "до анализа — для прямого вызова это сигнал, что индексация "
             "не выполнялась.")


@tool
def repo_overview() -> str:
    """Сводка по репозиторию из Repo Map: размер, языки, число точек
    входа и sink-ов по видам. Вызови первой, чтобы понять масштаб цели."""
    store = _open()
    if store is None:
        return _NO_INDEX
    try:
        s = Q.summary(store)
    finally:
        store.close()
    return (
        f"Корень: {s['root']}\nКоммит: {s['commit'] or 'n/a'}\n"
        f"Файлов: {s['files']}, строк кода: {s['loc']}\n"
        f"Языки: {s['languages']}\nРоли файлов: {s['roles']}\n"
        f"Символов: {s['symbols']}\n"
        f"Точек входа (attack surface): {s['entry_points']}\n"
        f"Sink-ов: {s['sinks']} по видам {s['sink_kinds']}"
    )


@tool
def find_entry_points(kind: str = "") -> str:
    """Точки входа репозитория (attack surface): HTTP-роуты, CLI,
    обработчики. kind — фильтр (http_route/cli/handler/main) или пусто.
    Начинай анализ отсюда: недоверенный ввод входит через них."""
    store = _open()
    if store is None:
        return _NO_INDEX
    try:
        rows = Q.entry_points(store, kind or None)
    finally:
        store.close()
    return _fmt(rows, "{file}:{line}  [{kind}] {name}  ({detail})",
                empty="Точек входа не найдено.")


@tool
def find_sinks(kind: str = "") -> str:
    """Опасные операции (sink-и): sql, command, deserialization, eval,
    file, crypto, ssrf. kind — фильтр по виду или пусто для всех.
    Это кандидаты уязвимостей — проверь достижимость от точек входа."""
    store = _open()
    if store is None:
        return _NO_INDEX
    try:
        rows = Q.sinks(store, kind or None)
    finally:
        store.close()
    return _fmt(rows, "{file}:{line}  [{kind}]  {snippet}",
                empty="Sink-ов не найдено.")


@tool
def find_symbol(name: str) -> str:
    """Определения символа (функция/класс/метод) по имени или подстроке.
    Возвращает `file:line` — читай потом точечно нужный диапазон."""
    store = _open()
    if store is None:
        return _NO_INDEX
    try:
        rows = Q.symbol_lookup(store, name)
    finally:
        store.close()
    return _fmt(rows, "{file}:{line}-{end_line}  {kind} {name}",
                empty=f"Символ '{name}' не найден.")


@tool
def who_calls(name: str) -> str:
    """Места вызова функции/метода по имени — для трассировки source→sink:
    «кто дёргает эту опасную операцию»."""
    store = _open()
    if store is None:
        return _NO_INDEX
    try:
        rows = Q.who_calls(store, name)
    finally:
        store.close()
    return _fmt(rows, "{file}:{line}  {caller} -> {callee}",
                empty=f"Вызовов '{name}' не найдено.")


@tool
def file_symbols(path: str) -> str:
    """Карта символов файла (имена + диапазоны строк) без чтения целиком —
    навигация по большому файлу."""
    store = _open()
    if store is None:
        return _NO_INDEX
    try:
        rows = Q.file_outline(store, path)
    finally:
        store.close()
    return _fmt(rows, "{line}-{end_line}  {kind} {name}",
                empty=f"Символы в '{path}' не найдены (нет файла в индексе).")


def repo_map_tools() -> list:
    """Список инструментов Repo Map для подключения к агентам."""
    return [repo_overview, find_entry_points, find_sinks,
            find_symbol, who_calls, file_symbols]
