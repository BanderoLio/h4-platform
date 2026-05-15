import hashlib
import hmac
import json
import os
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")
COMMENT_TEMPLATE = os.getenv(
    "PR_COMMENT_TEMPLATE",
    "Automated test comment for `{repo}` PR #{pr_number} (action: `{action}`).",
)
ALLOWED_PR_ACTIONS = {"opened", "reopened", "synchronize", "ready_for_review"}

app = FastAPI(title="GitHub Webhook Test Backend", version="0.1.0")


def _verify_signature(body: bytes, signature_header: str | None) -> None:
    if not WEBHOOK_SECRET:
        return

    if not signature_header:
        raise HTTPException(status_code=401, detail="Missing X-Hub-Signature-256 header")

    expected = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, signature_header):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")


async def _post_pr_comment(owner: str, repo: str, pr_number: int, body: str) -> dict[str, Any]:
    if not GITHUB_TOKEN:
        raise HTTPException(
            status_code=500,
            detail="GITHUB_TOKEN is not set. Cannot send PR comment.",
        )

    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{pr_number}/comments"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(url, headers=headers, json={"body": body})

    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "GitHub API error while creating PR comment",
                "status_code": response.status_code,
                "response": response.text,
            },
        )

    return response.json()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/webhooks/github")
async def github_webhook(
    request: Request,
    x_github_event: str | None = Header(default=None),
    x_github_delivery: str | None = Header(default=None),
    x_hub_signature_256: str | None = Header(default=None),
) -> dict[str, Any]:
    body = await request.body()
    _verify_signature(body, x_hub_signature_256)

    if not x_github_event:
        raise HTTPException(status_code=400, detail="Missing X-GitHub-Event header")

    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    if x_github_event == "ping":
        return {"ok": True, "event": "ping", "delivery": x_github_delivery}

    if x_github_event != "pull_request":
        return {
            "ok": True,
            "event": x_github_event,
            "delivery": x_github_delivery,
            "ignored": True,
            "reason": "Only pull_request events are handled",
        }

    action = payload.get("action")
    if action not in ALLOWED_PR_ACTIONS:
        return {
            "ok": True,
            "event": x_github_event,
            "delivery": x_github_delivery,
            "ignored": True,
            "reason": f"Action '{action}' is not in {sorted(ALLOWED_PR_ACTIONS)}",
        }

    repository = payload.get("repository") or {}
    pr = payload.get("pull_request") or {}
    owner = ((repository.get("owner") or {}).get("login")) or ""
    repo_name = repository.get("name") or ""
    pr_number = pr.get("number")
    pr_title = pr.get("title") or "Untitled PR"

    if not owner or not repo_name or not isinstance(pr_number, int):
        raise HTTPException(status_code=400, detail="Missing repository or PR data in payload")

    comment_body = COMMENT_TEMPLATE.format(
        owner=owner,
        repo=repo_name,
        pr_number=pr_number,
        action=action,
        pr_title=pr_title,
    )
    comment = await _post_pr_comment(owner, repo_name, pr_number, comment_body)

    return {
        "ok": True,
        "event": x_github_event,
        "delivery": x_github_delivery,
        "repository": f"{owner}/{repo_name}",
        "pr_number": pr_number,
        "comment_id": comment.get("id"),
        "comment_url": comment.get("html_url"),
    }
