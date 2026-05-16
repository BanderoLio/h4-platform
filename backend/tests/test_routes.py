import pytest

from tests.conftest import AUTH


@pytest.mark.asyncio
async def test_start_scan_returns_session_id_from_agentsec(client, monkeypatch):
    called = {}

    def fake_start_session(*, task, repo, interactive):
        called["task"] = task
        called["repo"] = repo
        called["interactive"] = interactive
        return "sess-123"

    monkeypatch.setattr("app.routes.scan.start_session", fake_start_session)

    resp = await client.post(
        "/scan/start",
        json={"repo_url": "https://github.com/example/repo"},
        headers=AUTH,
    )
    assert resp.status_code == 202
    assert resp.json() == {"scan_id": "sess-123"}
    assert called == {
        "task": "Security scan for repository https://github.com/example/repo",
        "repo": "https://github.com/example/repo",
        "interactive": True,
    }


@pytest.mark.asyncio
async def test_start_scan_passes_interactive_flag(client, monkeypatch):
    called = {}

    def fake_start_session(*, task, repo, interactive):
        called["interactive"] = interactive
        return "sess-123"

    monkeypatch.setattr("app.routes.scan.start_session", fake_start_session)

    resp = await client.post(
        "/scan/start",
        json={"repo_url": "https://github.com/example/repo", "interactive": False},
        headers=AUTH,
    )
    assert resp.status_code == 202
    assert called["interactive"] is False


@pytest.mark.asyncio
async def test_start_scan_uses_query_as_task(client, monkeypatch):
    called = {}

    def fake_start_session(*, task, repo, interactive):
        called["task"] = task
        return "sess-123"

    monkeypatch.setattr("app.routes.scan.start_session", fake_start_session)

    resp = await client.post(
        "/scan/start",
        json={
            "repo_url": "https://github.com/example/repo",
            "query": "find hardcoded secrets",
            "interactive": True,
        },
        headers=AUTH,
    )
    assert resp.status_code == 202
    assert called["task"] == "find hardcoded secrets"


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
async def test_start_scan_rejects_invalid_url(client):
    resp = await client.post(
        "/scan/start",
        json={"repo_url": "string"},
        headers=AUTH,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_start_scan_rejects_loopback_repo_url(client):
    resp = await client.post(
        "/scan/start",
        json={"repo_url": "http://127.0.0.1/nope"},
        headers=AUTH,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_start_scan_rejects_loopback_webhook_url(client):
    resp = await client.post(
        "/scan/start",
        json={
            "repo_url": "https://github.com/example/repo",
            "webhook_url": "http://127.0.0.1/hook",
        },
        headers=AUTH,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_start_scan_returns_503_when_session_layer_unavailable(client, monkeypatch):
    def fake_start_session(*, task, repo, interactive):
        raise RuntimeError("session backend down")

    monkeypatch.setattr("app.routes.scan.start_session", fake_start_session)
    resp = await client.post(
        "/scan/start",
        json={"repo_url": "https://github.com/example/repo"},
        headers=AUTH,
    )
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_get_report_running(client, monkeypatch):
    monkeypatch.setattr(
        "app.routes.scan.get_session",
        lambda session_id: {"id": session_id, "status": "running", "report_md": None},
    )
    resp = await client.get("/scan/sess-1/report", headers=AUTH)
    assert resp.status_code == 202
    assert resp.json() == {"status": "running", "report": None}


@pytest.mark.asyncio
async def test_get_report_completed(client, monkeypatch):
    monkeypatch.setattr(
        "app.routes.scan.get_session",
        lambda session_id: {"id": session_id, "status": "completed", "report_md": "found: nothing"},
    )
    resp = await client.get("/scan/sess-1/report", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json() == {"status": "completed", "report": "found: nothing"}


@pytest.mark.asyncio
async def test_get_report_awaiting_input(client, monkeypatch):
    monkeypatch.setattr(
        "app.routes.scan.get_session",
        lambda session_id: {"id": session_id, "status": "awaiting_input", "report_md": None},
    )
    resp = await client.get("/scan/sess-1/report", headers=AUTH)
    assert resp.status_code == 202
    assert resp.json() == {"status": "awaiting_input", "report": None}


@pytest.mark.asyncio
async def test_get_report_not_found(client, monkeypatch):
    from app.routes.scan import SessionNotFoundError

    def fake_get_session(session_id: str):
        raise SessionNotFoundError(session_id)

    monkeypatch.setattr("app.routes.scan.get_session", fake_get_session)

    resp = await client.get("/scan/nonexistent-id/report", headers=AUTH)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "scan not found"


@pytest.mark.asyncio
async def test_list_sessions(client, monkeypatch):
    monkeypatch.setattr(
        "app.routes.scan.list_sessions",
        lambda limit, offset: [
            {
                "id": "s-1",
                "status": "running",
                "repo": "https://github.com/example/repo",
                "task": "scan",
                "created_at": "2026-01-01T00:00:00",
                "updated_at": "2026-01-01T00:00:01",
            }
        ],
    )
    resp = await client.get("/scan/sessions?limit=10&offset=5", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json() == {
        "items": [
            {
                "id": "s-1",
                "status": "running",
                "repo": "https://github.com/example/repo",
                "task": "scan",
                "created_at": "2026-01-01T00:00:00",
                "updated_at": "2026-01-01T00:00:01",
            }
        ],
        "limit": 10,
        "offset": 5,
    }


@pytest.mark.asyncio
async def test_resume_scan(client, monkeypatch):
    called = {}

    def fake_resume_session(session_id, answer):
        called["session_id"] = session_id
        called["answer"] = answer

    monkeypatch.setattr("app.routes.scan.resume_session", fake_resume_session)

    resp = await client.post(
        "/scan/s-1/resume",
        json={"answer": "continue"},
        headers=AUTH,
    )
    assert resp.status_code == 202
    assert called == {"session_id": "s-1", "answer": "continue"}


@pytest.mark.asyncio
async def test_resume_scan_conflict_when_not_awaiting_input(client, monkeypatch):
    from app.routes.scan import InvalidSessionStateError

    def fake_resume_session(session_id, answer):
        raise InvalidSessionStateError("completed")

    monkeypatch.setattr("app.routes.scan.resume_session", fake_resume_session)
    resp = await client.post(
        "/scan/s-1/resume",
        json={"answer": "continue"},
        headers=AUTH,
    )
    assert resp.status_code == 409
