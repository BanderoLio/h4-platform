"""MCP-сервер для управления сессиями анализа agentsec.

Сервер специально сделан тонким: он не трогает оркестратор и
проксирует вызовы в уже существующий фасад `agentsec.session`.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # .env необязателен, если окружение уже выставлено.
    def load_dotenv() -> bool:
        return False


def _import_fastmcp():
    """Импортирует FastMCP, обходя конфликт с локальной папкой `mcp/`."""
    repo_root = str(Path(__file__).resolve().parents[1])
    removed: list[tuple[int, str]] = []
    for index in range(len(sys.path) - 1, -1, -1):
        entry = sys.path[index]
        if entry in {"", repo_root}:
            removed.append((index, entry))
            sys.path.pop(index)
    try:
        from mcp.server.fastmcp import FastMCP as _FastMCP
    finally:
        for index, entry in sorted(removed, key=lambda item: item[0]):
            sys.path.insert(index, entry)
    return _FastMCP


FastMCP = _import_fastmcp()

from agentsec.persistence.store import SessionRecord
from agentsec.session import (
    get_session as get_session_api,
    list_sessions as list_sessions_api,
    resume_session as resume_session_api,
    start_session as start_session_api,
)

load_dotenv()
mcp = FastMCP("agentsec")


def _serialize_session(session: SessionRecord | None) -> dict[str, Any] | None:
    return session.to_dict() if session is not None else None


@mcp.tool()
def start_analysis(task: str, repo: str, interactive: bool = True) -> dict[str, Any]:
    """Поставить новый анализ в очередь и вернуть id сессии."""
    repo_path = str(Path(repo).expanduser().resolve())
    session_id = start_session_api(task=task, repo=repo_path, interactive=interactive)
    return {
        "session_id": session_id,
        "status": "queued",
        "session": _serialize_session(get_session_api(session_id)),
    }


@mcp.tool()
def get_session(session_id: str) -> dict[str, Any]:
    """Получить текущее состояние сессии анализа по id."""
    return {
        "session_id": session_id,
        "session": _serialize_session(get_session_api(session_id)),
    }


@mcp.tool()
def resume_session(session_id: str, answer: str) -> dict[str, Any]:
    """Передать ответ пользователя и продолжить сессию из паузы."""
    resume_session_api(session_id=session_id, answer=answer)
    return {
        "session_id": session_id,
        "status": "queued",
        "session": _serialize_session(get_session_api(session_id)),
    }


@mcp.tool()
def list_sessions(limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """Вернуть историю сессий (новые сверху) с пагинацией."""
    if limit < 1:
        raise ValueError("limit должен быть >= 1")
    if offset < 0:
        raise ValueError("offset должен быть >= 0")
    sessions = list_sessions_api(limit=limit, offset=offset)
    return {
        "items": [session.to_dict() for session in sessions],
        "limit": limit,
        "offset": offset,
    }


def main() -> None:
    """Запуск MCP-сервера через stdio transport."""
    mcp.run()


if __name__ == "__main__":
    main()

