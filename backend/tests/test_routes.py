import pytest
from unittest.mock import AsyncMock
from tests.conftest import AUTH


@pytest.mark.asyncio
async def test_start_scan_returns_scan_id(client, mock_arq):
    resp = await client.post(
        "/scan/start",
        json={"repo_url": "https://github.com/example/repo"},
        headers=AUTH,
    )
    assert resp.status_code == 202
    data = resp.json()
    assert "scan_id" in data
    assert len(data["scan_id"]) == 36  # uuid4


@pytest.mark.asyncio
async def test_start_scan_enqueues_job(client, mock_arq):
    resp = await client.post(
        "/scan/start",
        json={"repo_url": "https://github.com/example/repo"},
        headers=AUTH,
    )
    scan_id = resp.json()["scan_id"]
    mock_arq.enqueue_job.assert_awaited_once_with(
        "run_scan", scan_id, "https://github.com/example/repo", None, None,
    )


@pytest.mark.asyncio
async def test_start_scan_requires_auth(client):
    resp = await client.post(
        "/scan/start",
        json={"repo_url": "https://github.com/example/repo"},
    )
    assert resp.status_code == 403  # HTTPBearer returns 403 when header missing


@pytest.mark.asyncio
async def test_start_scan_rejects_wrong_key(client):
    resp = await client.post(
        "/scan/start",
        json={"repo_url": "https://github.com/example/repo"},
        headers={"Authorization": "Bearer wrong-key"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_start_scan_rejects_invalid_url(client, mock_arq):
    resp = await client.post(
        "/scan/start",
        json={"repo_url": "string"},
        headers=AUTH,
    )
    assert resp.status_code == 422
    mock_arq.enqueue_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_start_scan_rejects_loopback_repo_url(client, mock_arq):
    resp = await client.post(
        "/scan/start",
        json={"repo_url": "http://127.0.0.1/nope"},
        headers=AUTH,
    )
    assert resp.status_code == 422
    mock_arq.enqueue_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_start_scan_rejects_loopback_webhook_url(client, mock_arq):
    resp = await client.post(
        "/scan/start",
        json={
            "repo_url": "https://github.com/example/repo",
            "webhook_url": "http://127.0.0.1/hook",
        },
        headers=AUTH,
    )
    assert resp.status_code == 422
    mock_arq.enqueue_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_start_scan_marks_failed_when_enqueue_unavailable(client, mock_arq):
    from app import db as db_module

    mock_arq.enqueue_job.side_effect = ConnectionError("redis down")
    resp = await client.post(
        "/scan/start",
        json={"repo_url": "https://github.com/example/repo"},
        headers=AUTH,
    )
    assert resp.status_code == 503

    # The DB row must exist and be marked failed so callers don't get orphaned running status
    from sqlalchemy import select
    from app import database
    from app.models import Scan
    async with database.AsyncSessionLocal() as session:
        result = await session.execute(select(Scan).where(Scan.status == "failed"))
        row = result.scalars().first()
    assert row is not None


@pytest.mark.asyncio
async def test_get_report_running(client, mock_arq):
    start = await client.post(
        "/scan/start",
        json={"repo_url": "https://github.com/example/repo"},
        headers=AUTH,
    )
    scan_id = start.json()["scan_id"]

    resp = await client.get(f"/scan/{scan_id}/report", headers=AUTH)
    assert resp.status_code == 202
    assert resp.json() == {"status": "running", "report": None}


@pytest.mark.asyncio
async def test_get_report_done(client, mock_arq):
    from app import db as db_module

    start = await client.post(
        "/scan/start",
        json={"repo_url": "https://github.com/example/repo"},
        headers=AUTH,
    )
    scan_id = start.json()["scan_id"]
    await db_module.update_scan(scan_id, "done", "found: nothing")

    resp = await client.get(f"/scan/{scan_id}/report", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json() == {"status": "done", "report": "found: nothing"}


@pytest.mark.asyncio
async def test_get_report_not_found(client):
    resp = await client.get("/scan/nonexistent-id/report", headers=AUTH)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "scan not found"
