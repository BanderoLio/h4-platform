import uuid

from arq import ArqRedis
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, HttpUrl, field_validator

from app.auth import require_api_key
from app.db import create_scan, get_scan, update_scan
from app.repo_url_validation import validate_worker_fetch_url

router = APIRouter(prefix="/scan", dependencies=[Depends(require_api_key)])


class StartScanRequest(BaseModel):
    repo_url: HttpUrl
    webhook_url: HttpUrl | None = None
    query: str | None = None

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


def get_arq(request: Request) -> ArqRedis:
    return request.app.state.arq


@router.post("/start", status_code=202, response_model=StartScanResponse)
async def start_scan(body: StartScanRequest, arq: ArqRedis = Depends(get_arq)):
    scan_id = str(uuid.uuid4())
    repo_url = str(body.repo_url)
    webhook_url = str(body.webhook_url) if body.webhook_url else None
    await create_scan(scan_id, repo_url, webhook_url)
    try:
        await arq.enqueue_job("run_scan", scan_id, repo_url, webhook_url, body.query)
    except Exception:
        await update_scan(scan_id, "failed", "Failed to enqueue scan job")
        raise HTTPException(status_code=503, detail="Queue unavailable, try again")
    return StartScanResponse(scan_id=scan_id)


@router.get("/{scan_id}/report", response_model=ReportResponse)
async def get_report(scan_id: str):
    row = await get_scan(scan_id)
    if row is None:
        raise HTTPException(status_code=404, detail="scan not found")
    status_code = 200 if row.status in ("done", "failed") else 202
    return JSONResponse(
        status_code=status_code,
        content={"status": row.status, "report": row.report},
    )
