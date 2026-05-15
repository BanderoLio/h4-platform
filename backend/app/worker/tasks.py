import asyncio
import shutil
from pathlib import Path

import httpx
from arq.connections import RedisSettings
from arq.worker import Retry
from git import GitCommandError, InvalidGitRepositoryError, Repo

from app.config import settings
from app.db import get_stuck_scans, update_scan, update_webhook_error
from app.repo_url_validation import validate_worker_fetch_url

_JOB_TIMEOUT = 3600  # seconds — ARQ kills and retries after this
_MAX_TRIES = 3       # total attempts including the first run
_WEBHOOK_RETRIES = 3

_TRANSIENT_ERRORS = (OSError, ConnectionError, TimeoutError, GitCommandError)


async def run_scan(
    ctx: dict,
    scan_id: str,
    repo_url: str,
    webhook_url: str | None,
    query: str | None = None,
) -> None:
    repo_path = Path(settings.repos_dir) / scan_id
    report: str | None = None
    try:
        await asyncio.to_thread(_sync_repo, repo_url, repo_path)
        report = await _run_agent_stub(scan_id, repo_path, query)
        await update_scan(scan_id, "done", report)
    except Exception as exc:
        job_try: int = ctx.get("job_try", 1)
        if isinstance(exc, _TRANSIENT_ERRORS) and job_try < _MAX_TRIES:
            raise Retry(defer=2 ** job_try)
        try:
            await update_scan(scan_id, "failed", str(exc))
        except Exception:
            pass
        raise
    finally:
        await asyncio.to_thread(_cleanup_repo, repo_path)

    if webhook_url and report is not None:
        try:
            validate_worker_fetch_url(webhook_url)
            await _deliver_webhook(webhook_url, scan_id, report)
        except Exception as exc:
            try:
                await update_webhook_error(scan_id, str(exc))
            except Exception:
                pass


def _sync_repo(repo_url: str, repo_path: Path) -> None:
    validate_worker_fetch_url(repo_url)
    if repo_path.exists():
        try:
            repo = Repo(repo_path)
            repo.remotes.origin.fetch()
            repo.git.reset("--hard", "origin/HEAD")
            return
        except InvalidGitRepositoryError:
            shutil.rmtree(repo_path)
    repo_path.parent.mkdir(parents=True, exist_ok=True)
    Repo.clone_from(repo_url, repo_path)


def _cleanup_repo(repo_path: Path) -> None:
    if repo_path.exists():
        shutil.rmtree(repo_path, ignore_errors=True)


async def _run_agent_stub(scan_id: str, repo_path: Path, query: str | None) -> str:
    await asyncio.sleep(10)
    suffix = f" | query: {query}" if query else ""
    return f"[stub] scan complete for {repo_path.name}{suffix}"


async def _deliver_webhook(webhook_url: str, scan_id: str, report: str) -> None:
    last_exc: Exception | None = None
    for attempt in range(_WEBHOOK_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    webhook_url,
                    json={"scan_id": scan_id, "report": report},
                    headers={"Authorization": f"Bearer {settings.webhook_token}"},
                )
                resp.raise_for_status()
                return
        except Exception as exc:
            last_exc = exc
            if attempt < _WEBHOOK_RETRIES - 1:
                await asyncio.sleep(2 ** attempt)
    raise last_exc  # type: ignore[misc]


async def _reconcile_stuck_scans(ctx: dict) -> None:
    """On startup, mark scans stuck at 'running' as failed.

    Covers the case where the worker was killed mid-scan and the DB row
    was never updated. ARQ will retry the job; this ensures callers see
    a terminal status during the retry window rather than hanging forever.
    """
    for scan_id in await get_stuck_scans():
        try:
            await update_scan(scan_id, "failed", "Worker restarted before scan completed — will retry")
        except Exception:
            pass


class WorkerSettings:
    functions = [run_scan]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    job_timeout = _JOB_TIMEOUT
    max_tries = _MAX_TRIES
    on_startup = _reconcile_stuck_scans
