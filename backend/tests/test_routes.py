import pytest

from tests.conftest import AUTH


@pytest.fixture(autouse=True)
def _clear_pending_scans():
    """Keep the module-level pending-scan registry isolated between tests."""
    from app.routes import scan as scan_module

    yield
    with scan_module._pending_lock:
        scan_module._pending_scans.clear()


# For a repo_url scan the clone + start_session run in a FastAPI background
# task. With the ASGI test transport the background task completes within the
# `await client.post(...)` call, so `called` is already populated afterwards.


@pytest.mark.asyncio
async def test_start_scan_returns_session_id_from_agentsec(client, monkeypatch):
    called = {}

    def fake_start_session(*, task, repo, interactive, session_id=None, repo_url=None):
        called["task"] = task
        called["repo"] = repo
        called["interactive"] = interactive
        called["repo_url"] = repo_url
        called["session_id"] = session_id
        return session_id

    monkeypatch.setattr("app.routes.scan.start_session", fake_start_session)
    monkeypatch.setattr("app.routes.scan._clone_repo", lambda *_: "/tmp/local-repo")

    resp = await client.post(
        "/scan/start",
        json={"repo_url": "https://github.com/example/repo"},
        headers=AUTH,
    )
    assert resp.status_code == 202
    # /scan/start returns the scan_id it generated up front.
    scan_id = resp.json()["scan_id"]
    assert isinstance(scan_id, str) and scan_id
    assert called == {
        "task": "Security scan for repository https://github.com/example/repo",
        "repo": "/tmp/local-repo",
        "interactive": True,
        # repo_url (исходный git-URL) хранится отдельно от пути к клону —
        # по нему фронтенд связывает сессии со своим реестром репозиториев.
        "repo_url": "https://github.com/example/repo",
        "session_id": scan_id,
    }


@pytest.mark.asyncio
async def test_start_scan_passes_interactive_flag(client, monkeypatch):
    called = {}

    def fake_start_session(*, task, repo, interactive, session_id=None, repo_url=None):
        called["interactive"] = interactive
        return session_id

    monkeypatch.setattr("app.routes.scan.start_session", fake_start_session)
    monkeypatch.setattr("app.routes.scan._clone_repo", lambda *_: "/tmp/local-repo")

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

    def fake_start_session(*, task, repo, interactive, session_id=None, repo_url=None):
        called["task"] = task
        return session_id

    monkeypatch.setattr("app.routes.scan.start_session", fake_start_session)
    monkeypatch.setattr("app.routes.scan._clone_repo", lambda *_: "/tmp/local-repo")

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
async def test_start_scan_reports_failure_when_session_layer_unavailable(
    client, monkeypatch
):
    # For a repo_url scan, start_session runs in the background task. A
    # failure there surfaces via /report status "failed", not as a /start error.
    def fake_start_session(*, task, repo, interactive, session_id=None, repo_url=None):
        raise RuntimeError("session backend down")

    monkeypatch.setattr("app.routes.scan.start_session", fake_start_session)
    monkeypatch.setattr("app.routes.scan._clone_repo", lambda *_: "/tmp/local-repo")
    resp = await client.post(
        "/scan/start",
        json={"repo_url": "https://github.com/example/repo"},
        headers=AUTH,
    )
    assert resp.status_code == 202
    scan_id = resp.json()["scan_id"]

    report = await client.get(f"/scan/{scan_id}/report", headers=AUTH)
    assert report.status_code == 200
    assert report.json()["status"] == "failed"
    assert "session backend down" in (report.json()["report"] or "")


@pytest.mark.asyncio
async def test_start_scan_reports_failure_when_repo_clone_fails(client, monkeypatch):
    # A clone failure now surfaces via /report (the clone is a background task).
    def fake_clone_repo(*args):
        raise RuntimeError("failed to clone repository: boom")

    monkeypatch.setattr("app.routes.scan._clone_repo", fake_clone_repo)
    resp = await client.post(
        "/scan/start",
        json={"repo_url": "https://github.com/example/repo"},
        headers=AUTH,
    )
    assert resp.status_code == 202
    scan_id = resp.json()["scan_id"]

    report = await client.get(f"/scan/{scan_id}/report", headers=AUTH)
    assert report.status_code == 200
    assert report.json()["status"] == "failed"
    assert "clone" in (report.json()["report"] or "")


@pytest.mark.asyncio
async def test_get_report_running(client, monkeypatch):
    monkeypatch.setattr(
        "app.routes.scan.get_session",
        lambda session_id: {"id": session_id, "status": "running", "report_md": None},
    )
    resp = await client.get("/scan/sess-1/report", headers=AUTH)
    assert resp.status_code == 202
    assert resp.json() == {
        "status": "running",
        "report": None,
        "interrupt_type": None,
        "question": None,
    }


@pytest.mark.asyncio
async def test_get_report_completed(client, monkeypatch):
    monkeypatch.setattr(
        "app.routes.scan.get_session",
        lambda session_id: {"id": session_id, "status": "completed", "report_md": "found: nothing"},
    )
    resp = await client.get("/scan/sess-1/report", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json() == {
        "status": "completed",
        "report": "found: nothing",
        "interrupt_type": None,
        "question": None,
    }


@pytest.mark.asyncio
async def test_get_report_awaiting_input(client, monkeypatch):
    monkeypatch.setattr(
        "app.routes.scan.get_session",
        lambda session_id: {
            "id": session_id,
            "status": "awaiting_input",
            "report_md": None,
            "interrupt_type": "clarify",
            "interrupt_payload": {
                "type": "clarify",
                "question": "Which environment is this deployed to?",
            },
        },
    )
    resp = await client.get("/scan/sess-1/report", headers=AUTH)
    assert resp.status_code == 202
    assert resp.json() == {
        "status": "awaiting_input",
        "report": None,
        "interrupt_type": "clarify",
        "question": "Which environment is this deployed to?",
    }


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
                "repo": "/data/repos/s-1",
                "repo_url": "https://github.com/example/repo",
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
                "repo": "/data/repos/s-1",
                "repo_url": "https://github.com/example/repo",
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


@pytest.mark.asyncio
async def test_start_scan_requires_exactly_one_source(client):
    # Neither repo_url nor repo_path -> rejected by the model validator.
    resp = await client.post("/scan/start", json={}, headers=AUTH)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_start_scan_rejects_repo_path_when_disabled(client):
    # ALLOWED_LOCAL_ROOTS is unset in the test env -> local-path scanning off.
    resp = await client.post(
        "/scan/start",
        json={"repo_path": "/tmp/some/repo"},
        headers=AUTH,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_start_scan_accepts_repo_path(client, monkeypatch):
    called = {}

    def fake_start_session(*, task, repo, interactive, session_id=None, repo_url=None):
        called["repo"] = repo
        called["repo_url"] = repo_url
        return session_id

    monkeypatch.setattr("app.routes.scan.start_session", fake_start_session)
    monkeypatch.setattr("app.routes.scan._resolve_local_repo", lambda p: "/srv/code/app")

    resp = await client.post(
        "/scan/start",
        json={"repo_path": "/srv/code/app", "query": "audit"},
        headers=AUTH,
    )
    assert resp.status_code == 202
    assert isinstance(resp.json()["scan_id"], str) and resp.json()["scan_id"]
    assert called["repo"] == "/srv/code/app"
    # A local-path scan has no git URL.
    assert called["repo_url"] is None


@pytest.mark.asyncio
async def test_get_result_completed(client, monkeypatch):
    monkeypatch.setattr(
        "app.routes.scan.get_session",
        lambda session_id: {
            "id": session_id,
            "status": "completed",
            "task": "audit",
            "repo": "/srv/code/app",
            "verdict": {"verdict": "FAIL", "total_findings": 1, "blocking": ["F-001"],
                        "severity_counts": {"High": 1}},
            "findings": [{"id": "F-001", "title": "SQLi", "severity": "High",
                          "file": "app/db.py:42", "cwe": "CWE-89"}],
            "coverage": [{"area": "injection", "status": "done"}],
        },
    )
    resp = await client.get("/scan/sess-1/result", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "completed"
    assert body["summary"]["verdict"] == "FAIL"
    assert body["summary"]["exit_code"] == 1
    assert len(body["problems"]) == 1
    problem = body["problems"][0]
    assert problem["id"] == "F-001"
    assert problem["file"] == "app/db.py"
    assert problem["line"] == 42


@pytest.mark.asyncio
async def test_get_result_running(client, monkeypatch):
    monkeypatch.setattr(
        "app.routes.scan.get_session",
        lambda session_id: {"id": session_id, "status": "running"},
    )
    resp = await client.get("/scan/sess-1/result", headers=AUTH)
    assert resp.status_code == 202
    assert resp.json()["status"] == "running"
    assert resp.json()["problems"] == []


@pytest.fixture
def pending_scan():
    """Register a scan whose repository is still cloning, then clean it up."""
    from app.routes import scan as scan_module

    scan_id = "pending-clone-scan"
    with scan_module._pending_lock:
        scan_module._pending_scans[scan_id] = scan_module._PendingScan(
            scan_id=scan_id,
            task="audit",
            repo_url="https://github.com/example/repo",
        )
    yield scan_id
    with scan_module._pending_lock:
        scan_module._pending_scans.pop(scan_id, None)


@pytest.mark.asyncio
async def test_report_is_running_while_repo_is_cloning(client, pending_scan):
    # A scan whose clone is still in progress must report as running (202),
    # not 404 — clients poll /report right after /scan/start returns.
    resp = await client.get(f"/scan/{pending_scan}/report", headers=AUTH)
    assert resp.status_code == 202
    assert resp.json()["status"] == "running"


@pytest.mark.asyncio
async def test_resume_conflicts_while_repo_is_cloning(client, pending_scan):
    resp = await client.post(
        f"/scan/{pending_scan}/resume", json={"answer": "x"}, headers=AUTH
    )
    assert resp.status_code == 409
