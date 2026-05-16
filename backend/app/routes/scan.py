import shutil
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from git import Repo
from pydantic import BaseModel, ConfigDict, HttpUrl, field_validator, model_validator

from app.auth import require_api_key
from app.config import settings
from app.repo_url_validation import validate_worker_fetch_url

_repo_root = Path(__file__).resolve().parents[3]
if str(_repo_root) not in sys.path:
    sys.path.append(str(_repo_root))

# Core session API and the optional structured-result helper are imported
# separately: a deployment may ship a minimal agentsec (e.g. the dev stub
# without `reporting`), and a missing `reporting` must not disable the
# primary /scan endpoints — only the machine-readable /result route.
try:  # pragma: no cover - exercised in integration envs
    from agentsec.session import get_session, list_sessions, resume_session, start_session
except Exception:
    get_session = None
    list_sessions = None
    resume_session = None
    start_session = None

try:  # pragma: no cover - exercised in integration envs
    from agentsec.reporting import build_structured_result
except Exception:
    build_structured_result = None

router = APIRouter(prefix="/scan", dependencies=[Depends(require_api_key)])


class StartScanRequest(BaseModel):
    # Источник кода: либо публичный git-URL для клонирования (repo_url),
    # либо абсолютный путь на стороне сервера (repo_path) — ровно один из двух.
    repo_url: HttpUrl | None = None
    repo_path: str | None = None
    webhook_url: HttpUrl | None = None
    query: str | None = None
    interactive: bool = True

    @field_validator("repo_url")
    @classmethod
    def repo_must_be_http(cls, v: HttpUrl | None) -> HttpUrl | None:
        if v is None:
            return None
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

    @model_validator(mode="after")
    def exactly_one_source(self) -> "StartScanRequest":
        if bool(self.repo_url) == bool(self.repo_path):
            raise ValueError("provide exactly one of repo_url or repo_path")
        return self


class StartScanResponse(BaseModel):
    scan_id: str


class ReportResponse(BaseModel):
    status: str
    report: str | None
    # Когда скан стоит на паузе (`awaiting_input`) — тип паузы и текст
    # вопроса агента, которые фронтенд показывает пользователю перед
    # вызовом `/resume`. Для остальных статусов оба поля — null.
    interrupt_type: str | None = None
    question: str | None = None


class ResumeScanRequest(BaseModel):
    answer: str


class SessionSummary(BaseModel):
    id: str
    status: str
    repo: str | None = None
    # Исходный git-URL репозитория (если скан запускался по repo_url).
    # Фронтенд связывает сессии со своим реестром репозиториев именно по
    # нему: `repo` хранит путь к клону на сервере и для этого не годится.
    repo_url: str | None = None
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


# --- pending clones ----------------------------------------------------------
# Cloning a repository can take minutes. /scan/start must not block on it: a
# blocking clone inside the async endpoint would freeze the whole event loop
# (every request, including /health, would hang). So a repo_url scan is
# registered here and cloned in a background task. While the entry lives here
# the scan already "exists" for /report (status "running"); a clone failure
# surfaces as status "failed". agentsec only sees the scan once the clone
# succeeds, after which the entry is dropped.


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class _PendingScan:
    scan_id: str
    task: str
    repo_url: str | None
    status: str = "running"  # "running" while cloning, "failed" on clone error
    error: str | None = None
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)


_pending_lock = Lock()
_pending_scans: dict[str, _PendingScan] = {}


def _get_pending(scan_id: str) -> _PendingScan | None:
    with _pending_lock:
        return _pending_scans.get(scan_id)


def _mark_pending_failed(scan_id: str, message: str) -> None:
    with _pending_lock:
        pending = _pending_scans.get(scan_id)
        if pending is not None:
            pending.status = "failed"
            pending.error = message
            pending.updated_at = _utc_now()


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


def _repos_base_dir() -> Path:
    """Каталог под клонированные репозитории (`REPOS_DIR`). Клоны не удаляются
    после скана (история сканов и возможность повторного анализа) и
    раскладываются по scan_id: `<REPOS_DIR>/<scan_id>`."""
    base_dir = Path(settings.repos_dir)
    try:
        base_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        # Local dev often uses docker-oriented REPOS_DIR=/data/repos (not writable on host).
        # Fallback keeps API usable without forcing immediate env changes.
        base_dir = Path(tempfile.gettempdir()) / "hack4" / "repos"
        base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def _clone_repo(repo_url: str, scan_id: str) -> str:
    """Клонирует репозиторий в постоянный каталог, привязанный к scan_id.

    Делается поверхностный клон (`--depth 1`): для анализа кода история git
    не нужна, а большие репозитории так клонируются в разы быстрее. Функция
    вызывается из фоновой задачи — поднимает обычное исключение, не
    HTTPException.
    """
    repo_path = _repos_base_dir() / scan_id
    if repo_path.exists():
        shutil.rmtree(repo_path, ignore_errors=True)
    try:
        Repo.clone_from(repo_url, repo_path, depth=1)
    except Exception as exc:
        shutil.rmtree(repo_path, ignore_errors=True)
        raise RuntimeError(f"failed to clone repository: {exc}") from exc
    return str(repo_path)


def _clone_then_start(
    scan_id: str, repo_url: str, task: str, interactive: bool
) -> None:
    """Фоновая задача: клонирует репозиторий и передаёт скан в agentsec.

    Запускается через FastAPI BackgroundTasks (синхронная функция → пул
    потоков), поэтому не блокирует event loop. Ошибки клонирования или
    старта сессии фиксируются в `_pending_scans` как статус `failed` —
    клиент узнаёт о них поллингом `/report`, как о любом падении скана.
    """
    try:
        repo_path = _clone_repo(repo_url, scan_id)
    except Exception as exc:  # noqa: BLE001 — фон не должен падать молча
        _mark_pending_failed(scan_id, str(exc))
        return
    try:
        start_session(
            task=task,
            repo=repo_path,
            interactive=interactive,
            session_id=scan_id,
            repo_url=repo_url,
        )
    except Exception as exc:  # noqa: BLE001
        _mark_pending_failed(scan_id, f"failed to start scan: {exc}")
        return
    # agentsec теперь владеет сессией — убираем временную запись.
    with _pending_lock:
        _pending_scans.pop(scan_id, None)


def _resolve_local_repo(repo_path: str) -> str:
    """Проверяет серверный путь репозитория против списка разрешённых корней.

    Сканирование по локальному пути включается оператором через
    `ALLOWED_LOCAL_ROOTS`; путь обязан лежать внутри одного из этих корней —
    это исключает чтение произвольных каталогов сервера.
    """
    roots = settings.local_root_paths
    if not roots:
        raise HTTPException(
            status_code=403,
            detail="local path scanning is disabled (set ALLOWED_LOCAL_ROOTS)",
        )
    try:
        resolved = Path(repo_path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        raise HTTPException(status_code=422, detail="repo_path does not exist")
    if not resolved.is_dir():
        raise HTTPException(status_code=422, detail="repo_path is not a directory")
    if not any(resolved == root or resolved.is_relative_to(root) for root in roots):
        raise HTTPException(
            status_code=403, detail="repo_path is outside the allowed roots"
        )
    return str(resolved)


@router.post("/start", status_code=202, response_model=StartScanResponse)
async def start_scan(body: StartScanRequest, background_tasks: BackgroundTasks):
    _require_session_api()
    # scan_id фиксируется заранее: каталог клона привязывается к нему,
    # и сессия agentsec создаётся с тем же id.
    scan_id = uuid.uuid4().hex

    if body.repo_path is not None:
        # Локальный путь: клонировать нечего, стартуем синхронно (быстро).
        local_repo_path = _resolve_local_repo(body.repo_path)
        task = body.query or f"Security scan for repository {local_repo_path}"
        try:
            start_session(
                task=task,
                repo=local_repo_path,
                interactive=body.interactive,
                session_id=scan_id,
                repo_url=None,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except Exception:
            raise HTTPException(status_code=503, detail="Session backend unavailable")
        return StartScanResponse(scan_id=scan_id)

    # repo_url: клонирование может длиться минуты. Регистрируем скан и
    # клонируем в фоновой задаче — запрос возвращается сразу (202), event
    # loop не блокируется. Запись в `_pending_scans` создаётся ДО ответа,
    # чтобы немедленный поллинг `/report` видел скан как `running`, а не 404.
    repo_url = str(body.repo_url)
    task = body.query or f"Security scan for repository {repo_url}"
    with _pending_lock:
        _pending_scans[scan_id] = _PendingScan(
            scan_id=scan_id, task=task, repo_url=repo_url
        )
    background_tasks.add_task(
        _clone_then_start, scan_id, repo_url, task, body.interactive
    )
    return StartScanResponse(scan_id=scan_id)


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
    pending = _get_pending(scan_id)
    if pending is not None:
        # Репозиторий ещё клонируется (`running`) или клон упал (`failed`).
        status_code = 200 if pending.status == "failed" else 202
        return JSONResponse(
            status_code=status_code,
            content={
                "status": pending.status,
                "report": pending.error,
                "interrupt_type": None,
                "question": None,
            },
        )
    row = _load_session_or_404(scan_id)
    status = _normalize_status(_read_field(row, "status"))
    report = _read_field(row, "report_md") or _read_field(row, "report")
    interrupt_type = None
    question = None
    if status == "awaiting_input":
        interrupt_type = _read_field(row, "interrupt_type")
        payload = _read_field(row, "interrupt_payload")
        if isinstance(payload, dict):
            question = payload.get("question")
    status_code = 200 if status in ("completed", "failed") else 202
    return JSONResponse(
        status_code=status_code,
        content={
            "status": status,
            "report": report,
            "interrupt_type": interrupt_type,
            "question": question,
        },
    )


@router.get("/{scan_id}/result")
async def get_result(scan_id: str):
    """Машиночитаемый результат скана для CI: `{summary, problems, coverage}`.

    `summary.exit_code` (0/1/2) — готовый код выхода для гейтинга пайплайна.
    Пока скан не завершён, отдаётся 202 с пустым `problems`.
    """
    _require_session_api()
    if build_structured_result is None:  # pragma: no cover - integration only
        raise HTTPException(status_code=503, detail="Session backend unavailable")
    pending = _get_pending(scan_id)
    if pending is not None:
        # Скан ещё клонируется или клон упал — agentsec его пока не видит.
        pending_status = "failed" if pending.status == "failed" else "running"
        result = build_structured_result(
            findings=[],
            verdict={},
            coverage=[],
            status=pending_status,
            scan_id=scan_id,
            task=pending.task,
            repo=pending.repo_url or "",
            error=pending.error,
        )
        status_code = 200 if pending_status == "failed" else 202
        return JSONResponse(status_code=status_code, content=result)
    row = _load_session_or_404(scan_id)
    status = _normalize_status(_read_field(row, "status"))
    result = build_structured_result(
        findings=_read_field(row, "findings") or [],
        verdict=_read_field(row, "verdict") or {},
        coverage=_read_field(row, "coverage") or [],
        status=status,
        scan_id=scan_id,
        task=_read_field(row, "task") or "",
        repo=_read_field(row, "repo") or "",
        error=_read_field(row, "error"),
    )
    status_code = 200 if status in ("completed", "failed") else 202
    return JSONResponse(status_code=status_code, content=result)


@router.post("/{scan_id}/resume", status_code=202)
async def resume_scan(scan_id: str, body: ResumeScanRequest):
    _require_session_api()
    if _get_pending(scan_id) is not None:
        # Скан ещё клонируется (или клон упал) — паузы на ввод тут быть не может.
        raise HTTPException(status_code=409, detail="scan is not awaiting input")
    try:
        resume_session(scan_id, body.answer)
    except InvalidSessionStateError:
        raise HTTPException(status_code=409, detail="scan is not awaiting input")
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="scan not found")
    except ValueError as exc:
        # agentsec.session.resume_session signals both "session missing" and
        # "session not awaiting input" via ValueError with a localized message.
        message = str(exc).lower()
        if "not found" in message or "missing" in message or "не найден" in message:
            raise HTTPException(status_code=404, detail="scan not found")
        # Any other ValueError from resume_session is a wrong-state error.
        raise HTTPException(status_code=409, detail="scan is not awaiting input")
    except Exception as exc:
        message = str(exc).lower()
        if "awaiting" in message:
            raise HTTPException(status_code=409, detail="scan is not awaiting input")
        if "not found" in message or "missing" in message:
            raise HTTPException(status_code=404, detail="scan not found")
        raise HTTPException(status_code=503, detail="Session backend unavailable")
    return {"status": "accepted"}
