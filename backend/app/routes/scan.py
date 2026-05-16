import shutil
import sys
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from git import GitCommandError, Repo
from pydantic import BaseModel, ConfigDict, HttpUrl, field_validator

from app.auth import require_api_key
from app.config import settings
from app.repo_url_validation import validate_worker_fetch_url

_repo_root = Path(__file__).resolve().parents[3]
if str(_repo_root) not in sys.path:
    sys.path.append(str(_repo_root))

try:
    from agentsec.session import get_session, list_sessions, resume_session, start_session
except Exception:  # pragma: no cover - exercised in integration envs
    get_session = None
    list_sessions = None
    resume_session = None
    start_session = None

router = APIRouter(prefix="/scan", dependencies=[Depends(require_api_key)])


class StartScanRequest(BaseModel):
    repo_url: HttpUrl
    webhook_url: HttpUrl | None = None
    query: str | None = None
    interactive: bool = True

    @field_validator("repo_url")
    @classmethod
    def repo_must_be_http(cls, v: HttpUrl) -> HttpUrl:
        if v.scheme not in ("http", "https"):
            raise ValueError("repo_url must use http or https")
        validate_worker_fetch_url(str(v))
        return v

    @field_validator("webhook_url")
    @classmethod
    def webhook_must_be_safe(cls, v: HttpUrl | None) -> HttpUrl | None:
        if v is None:
            return None
        validate_worker_fetch_url(str(v))
        return v


class StartScanResponse(BaseModel):
    scan_id: str


class ReportResponse(BaseModel):
    status: str
    report: str | None


class ResumeScanRequest(BaseModel):
    answer: str


class SessionSummary(BaseModel):
    id: str
    status: str
    repo: str | None = None
    task: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    model_config = ConfigDict(extra="allow")


class ListSessionsResponse(BaseModel):
    items: list[SessionSummary]
    limit: int
    offset: int


class SessionNotFoundError(Exception):
    pass


class InvalidSessionStateError(Exception):
    pass


def _require_session_api() -> None:
    if not all((start_session, get_session, resume_session, list_sessions)):
        raise HTTPException(status_code=503, detail="Session backend unavailable")


def _read_field(record: dict | object, field: str):
    if isinstance(record, dict):
        return record.get(field)
    return getattr(record, field, None)


def _normalize_status(status: str | None) -> str:
    if status == "done":
        return "completed"
    return status or "running"


def _load_session_or_404(scan_id: str) -> dict | object:
    try:
        session = get_session(scan_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="scan not found")
    except Exception as exc:
        message = str(exc).lower()
        if "not found" in message or "missing" in message:
            raise HTTPException(status_code=404, detail="scan not found")
        raise HTTPException(status_code=503, detail="Session backend unavailable")

    if session is None:
        raise HTTPException(status_code=404, detail="scan not found")
    return session


def _materialize_repo(repo_url: str) -> str:
    base_dir = Path(settings.repos_dir) / "session_sources"
    try:
        base_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        # Local dev often uses docker-oriented REPOS_DIR=/data/repos (not writable on host).
        # Fallback keeps API usable without forcing immediate env changes.
        base_dir = Path(tempfile.gettempdir()) / "hack4" / "session_sources"
        base_dir.mkdir(parents=True, exist_ok=True)
    repo_path = base_dir / uuid.uuid4().hex
    try:
        Repo.clone_from(repo_url, repo_path)
    except GitCommandError as exc:
        shutil.rmtree(repo_path, ignore_errors=True)
        raise HTTPException(status_code=422, detail=f"failed to clone repository: {exc}")
    except Exception:
        shutil.rmtree(repo_path, ignore_errors=True)
        raise HTTPException(status_code=503, detail="Failed to prepare repository for scan")
    return str(repo_path)


@router.post("/start", status_code=202, response_model=StartScanResponse)
async def start_scan(body: StartScanRequest):
    _require_session_api()
    repo_url = str(body.repo_url)
    task = body.query or f"Security scan for repository {repo_url}"
    local_repo_path = _materialize_repo(repo_url)
    try:
        session_id = start_session(task=task, repo=local_repo_path, interactive=body.interactive)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception:
        raise HTTPException(status_code=503, detail="Session backend unavailable")
    return StartScanResponse(scan_id=session_id)


@router.get("/sessions", response_model=ListSessionsResponse)
async def get_sessions(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    _require_session_api()
    try:
        records = list_sessions(limit=limit, offset=offset)
    except Exception:
        raise HTTPException(status_code=503, detail="Session backend unavailable")
    items = [SessionSummary.model_validate(record, from_attributes=True) for record in records]
    return ListSessionsResponse(items=items, limit=limit, offset=offset)


@router.get("/{scan_id}/report", response_model=ReportResponse)
async def get_report(scan_id: str):
    _require_session_api()
    row = _load_session_or_404(scan_id)
    status = _normalize_status(_read_field(row, "status"))
    report = _read_field(row, "report_md") or _read_field(row, "report")
    status_code = 200 if status in ("completed", "failed") else 202
    return JSONResponse(
        status_code=status_code,
        content={"status": status, "report": report},
    )


@router.post("/{scan_id}/resume", status_code=202)
async def resume_scan(scan_id: str, body: ResumeScanRequest):
    _require_session_api()
    try:
        resume_session(scan_id, body.answer)
    except InvalidSessionStateError:
        raise HTTPException(status_code=409, detail="scan is not awaiting input")
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="scan not found")
    except Exception as exc:
        message = str(exc).lower()
        if "awaiting" in message:
            raise HTTPException(status_code=409, detail="scan is not awaiting input")
        if "not found" in message or "missing" in message:
            raise HTTPException(status_code=404, detail="scan not found")
        raise HTTPException(status_code=503, detail="Session backend unavailable")
    return {"status": "accepted"}
