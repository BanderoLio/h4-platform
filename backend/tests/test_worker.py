import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app import db as db_module


@pytest.mark.asyncio
async def test_worker_sets_status_done(tmp_path):
    from app.worker.tasks import run_scan

    scan_id = "scan-worker-done"
    await db_module.create_scan(scan_id, "https://github.com/example/repo", None)

    with (
        patch("app.worker.tasks.settings") as mock_settings,
        patch("app.worker.tasks._sync_repo"),
        patch("app.worker.tasks._run_agent_stub", new_callable=AsyncMock) as mock_agent,
        patch("app.worker.tasks._cleanup_repo"),
    ):
        mock_settings.repos_dir = str(tmp_path)
        mock_agent.return_value = "stub report"

        await run_scan({}, scan_id, "https://github.com/example/repo", None)

    row = await db_module.get_scan(scan_id)
    assert row.status == "done"
    assert row.report == "stub report"


@pytest.mark.asyncio
async def test_worker_sets_status_failed_on_exception(tmp_path):
    from app.worker.tasks import run_scan

    scan_id = "scan-worker-fail"
    await db_module.create_scan(scan_id, "https://github.com/example/repo", None)

    with (
        patch("app.worker.tasks.settings") as mock_settings,
        patch("app.worker.tasks._sync_repo", side_effect=RuntimeError("clone failed")),
        patch("app.worker.tasks._cleanup_repo"),
    ):
        mock_settings.repos_dir = str(tmp_path)

        with pytest.raises(RuntimeError):
            await run_scan({}, scan_id, "https://github.com/example/repo", None)

    row = await db_module.get_scan(scan_id)
    assert row.status == "failed"


@pytest.mark.asyncio
async def test_worker_delivers_webhook(tmp_path):
    from app.worker.tasks import run_scan

    scan_id = "scan-webhook"
    await db_module.create_scan(scan_id, "https://github.com/example/repo", "https://example.org/hook")

    with (
        patch("app.worker.tasks.settings") as mock_settings,
        patch("app.worker.tasks._sync_repo"),
        patch("app.worker.tasks._run_agent_stub", new_callable=AsyncMock, return_value="report text"),
        patch("app.worker.tasks._cleanup_repo"),
        patch("app.worker.tasks._deliver_webhook", new_callable=AsyncMock) as mock_webhook,
    ):
        mock_settings.repos_dir = str(tmp_path)

        await run_scan({}, scan_id, "https://github.com/example/repo", "https://example.org/hook")

    mock_webhook.assert_awaited_once_with(
        "https://example.org/hook", scan_id, "report text"
    )


@pytest.mark.asyncio
async def test_worker_retries_transient_error_and_stays_running(tmp_path):
    """Transient errors (OSError, GitCommandError) trigger Retry, leave status 'running'."""
    from arq.worker import Retry
    from app.worker.tasks import run_scan

    scan_id = "scan-transient"
    await db_module.create_scan(scan_id, "https://github.com/example/repo", None)

    with (
        patch("app.worker.tasks.settings") as mock_settings,
        patch("app.worker.tasks._sync_repo", side_effect=OSError("network blip")),
        patch("app.worker.tasks._cleanup_repo"),
    ):
        mock_settings.repos_dir = str(tmp_path)
        with pytest.raises(Retry):
            await run_scan({"job_try": 1}, scan_id, "https://github.com/example/repo", None)

    row = await db_module.get_scan(scan_id)
    assert row.status == "running"  # not marked failed — will be retried


@pytest.mark.asyncio
async def test_worker_marks_failed_after_max_tries(tmp_path):
    """After max tries are exhausted, transient error is treated as permanent failure."""
    from arq.worker import Retry
    from app.worker.tasks import run_scan, _MAX_TRIES

    scan_id = "scan-max-tries"
    await db_module.create_scan(scan_id, "https://github.com/example/repo", None)

    with (
        patch("app.worker.tasks.settings") as mock_settings,
        patch("app.worker.tasks._sync_repo", side_effect=OSError("still failing")),
        patch("app.worker.tasks._cleanup_repo"),
    ):
        mock_settings.repos_dir = str(tmp_path)
        with pytest.raises(OSError):  # regular exception, not Retry
            await run_scan({"job_try": _MAX_TRIES}, scan_id, "https://github.com/example/repo", None)

    row = await db_module.get_scan(scan_id)
    assert row.status == "failed"


@pytest.mark.asyncio
async def test_worker_skips_webhook_when_none(tmp_path):
    from app.worker.tasks import run_scan

    scan_id = "scan-no-webhook"
    await db_module.create_scan(scan_id, "https://github.com/example/repo", None)

    with (
        patch("app.worker.tasks.settings") as mock_settings,
        patch("app.worker.tasks._sync_repo"),
        patch("app.worker.tasks._run_agent_stub", new_callable=AsyncMock, return_value="report"),
        patch("app.worker.tasks._cleanup_repo"),
        patch("app.worker.tasks._deliver_webhook", new_callable=AsyncMock) as mock_webhook,
    ):
        mock_settings.repos_dir = str(tmp_path)
        await run_scan({}, scan_id, "https://github.com/example/repo", None)

    mock_webhook.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_webhook_failure_stored_in_db(tmp_path):
    """Webhook delivery failure must be recorded; scan stays 'done'."""
    from app.worker.tasks import run_scan

    scan_id = "scan-webhook-fail"
    await db_module.create_scan(scan_id, "https://github.com/example/repo", "https://example.org/hook")

    with (
        patch("app.worker.tasks.settings") as mock_settings,
        patch("app.worker.tasks._sync_repo"),
        patch("app.worker.tasks._run_agent_stub", new_callable=AsyncMock, return_value="report"),
        patch("app.worker.tasks._cleanup_repo"),
        patch("app.worker.tasks._deliver_webhook", new_callable=AsyncMock, side_effect=ConnectionError("ci down")),
    ):
        mock_settings.repos_dir = str(tmp_path)
        await run_scan({}, scan_id, "https://github.com/example/repo", "https://example.org/hook")

    row = await db_module.get_scan(scan_id)
    assert row.status == "done"  # scan itself succeeded
    assert "ci down" in row.webhook_error


@pytest.mark.asyncio
async def test_webhook_retries_on_transient_failure():
    """_deliver_webhook retries up to 3 times before giving up."""
    from app.worker.tasks import _deliver_webhook

    attempt_count = 0

    async def flaky_post(*args, **kwargs):
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count < 3:
            raise ConnectionError("transient")
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        return mock_resp

    with (
        patch("app.worker.tasks.asyncio.sleep", new_callable=AsyncMock),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = flaky_post
        mock_client_cls.return_value = mock_client

        await _deliver_webhook("https://example.org/hook", "scan-id", "report")

    assert attempt_count == 3


@pytest.mark.asyncio
async def test_webhook_raises_after_all_retries_exhausted():
    from app.worker.tasks import _deliver_webhook

    with (
        patch("app.worker.tasks.asyncio.sleep", new_callable=AsyncMock),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=ConnectionError("always down"))
        mock_client_cls.return_value = mock_client

        with pytest.raises(ConnectionError):
            await _deliver_webhook("https://example.org/hook", "scan-id", "report")


@pytest.mark.asyncio
async def test_reconcile_marks_stuck_running_scans_failed():
    from app.worker.tasks import _reconcile_stuck_scans

    await db_module.create_scan("stuck-1", "https://github.com/example/repo", None)
    await db_module.create_scan("stuck-2", "https://github.com/example/repo", None)
    await db_module.update_scan("stuck-2", "done", "already done")  # should not be touched

    await _reconcile_stuck_scans({})

    row1 = await db_module.get_scan("stuck-1")
    row2 = await db_module.get_scan("stuck-2")
    assert row1.status == "failed"
    assert row2.status == "done"  # untouched


def test_sync_repo_clones_when_missing(tmp_path):
    from app.worker.tasks import _sync_repo

    repo_path = tmp_path / "new-repo"

    with patch("app.worker.tasks.Repo") as mock_repo_cls:
        _sync_repo("https://github.com/example/repo", repo_path)

    mock_repo_cls.clone_from.assert_called_once_with(
        "https://github.com/example/repo", repo_path
    )


def test_sync_repo_pulls_when_exists(tmp_path):
    from app.worker.tasks import _sync_repo

    repo_path = tmp_path / "existing-repo"
    repo_path.mkdir()

    mock_repo = MagicMock()
    mock_repo.remotes.origin.fetch = MagicMock()
    mock_repo.git.reset = MagicMock()

    with patch("app.worker.tasks.Repo", return_value=mock_repo) as mock_repo_cls:
        _sync_repo("https://github.com/example/repo", repo_path)

    mock_repo.remotes.origin.fetch.assert_called_once()
    mock_repo.git.reset.assert_called_once_with("--hard", "origin/HEAD")
    mock_repo_cls.clone_from.assert_not_called()


def test_sync_repo_reclones_corrupted(tmp_path):
    from app.worker.tasks import _sync_repo
    from git import InvalidGitRepositoryError

    repo_path = tmp_path / "corrupt-repo"
    repo_path.mkdir()

    with patch("app.worker.tasks.Repo", side_effect=[InvalidGitRepositoryError, MagicMock()]) as mock_repo_cls:
        _sync_repo("https://github.com/example/repo", repo_path)

    assert mock_repo_cls.clone_from.called
