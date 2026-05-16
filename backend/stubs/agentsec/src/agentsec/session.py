"""Session facade stub — mirrors the public API expected by hack4 FastAPI.

Real implementation lives in the agentsec orchestrator repo (see misty-singing-starfish.md).

Tests can force transitions via env `AGENTSEC_STUB_BEHAVIOR`:
- `running` (default): new sessions stay `running`.
- `instant_completed`: session immediately `completed` with a short report.
- `instant_failed`: session immediately `failed`.
- `awaiting_clarify`: immediately `awaiting_input` with interrupt_type `clarify`.
- `awaiting_gate`: immediately `awaiting_input` with interrupt_type `gate`.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SessionRecord:
    id: str
    title: str
    repo: str
    task: str
    status: str
    interrupt_type: str | None = None
    interrupt_payload: str | None = None
    verdict: str | None = None
    report_md: str | None = None
    error: str | None = None
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)


_lock = threading.Lock()
_sessions: dict[str, SessionRecord] = {}


def _behavior() -> str:
    return os.environ.get("AGENTSEC_STUB_BEHAVIOR", "running").strip().lower()


def _touch(rec: SessionRecord) -> None:
    rec.updated_at = _utc_now()


def start_session(task: str, repo: str, *, interactive: bool = True) -> str:
    """Create a session row and schedule analysis (stub: apply behavior immediately)."""
    sid = str(uuid.uuid4())
    title = (task or "").strip()[:60] or "(empty task)"
    behavior = _behavior()
    with _lock:
        rec = SessionRecord(
            id=sid,
            title=title,
            repo=repo,
            task=task,
            status="running",
        )
        if behavior == "instant_completed":
            rec.status = "completed"
            rec.report_md = f"[stub] completed for repo `{repo}`"
            _touch(rec)
        elif behavior == "instant_failed":
            rec.status = "failed"
            rec.error = "[stub] simulated failure"
            _touch(rec)
        elif behavior == "awaiting_clarify":
            if interactive:
                rec.status = "awaiting_input"
                rec.interrupt_type = "clarify"
                rec.interrupt_payload = json.dumps({"type": "clarify", "question": "Stub: any details?"})
            else:
                rec.status = "completed"
                rec.report_md = f"[stub] non-interactive skipped clarify for `{repo}`"
            _touch(rec)
        elif behavior == "awaiting_gate":
            if interactive:
                rec.status = "awaiting_input"
                rec.interrupt_type = "gate"
                rec.interrupt_payload = json.dumps(
                    {"type": "gate", "question": "Stub: approve?", "verdict": {"ok": True}}
                )
            else:
                rec.status = "completed"
                rec.report_md = f"[stub] non-interactive skipped gate for `{repo}`"
            _touch(rec)
        elif not interactive and behavior == "running":
            rec.status = "completed"
            rec.report_md = f"[stub] non-interactive run for `{repo}`"
            _touch(rec)
        _sessions[sid] = rec
    return sid


def resume_session(session_id: str, answer: Any) -> None:
    """Resume after interrupt (stub: mark completed with echo answer)."""
    with _lock:
        rec = _sessions.get(session_id)
        if rec is None:
            raise LookupError("session not found")
        if rec.status != "awaiting_input":
            raise RuntimeError("session is not awaiting input")
        rec.status = "completed"
        rec.interrupt_type = None
        rec.interrupt_payload = None
        rec.report_md = f"[stub] resumed; answer={answer!r}"
        _touch(rec)


def get_session(session_id: str) -> SessionRecord:
    with _lock:
        rec = _sessions.get(session_id)
        if rec is None:
            raise LookupError("session not found")
        return rec


def list_sessions(limit: int = 50, offset: int = 0) -> list[SessionRecord]:
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    with _lock:
        rows = sorted(_sessions.values(), key=lambda r: r.updated_at, reverse=True)
        return rows[offset : offset + limit]
