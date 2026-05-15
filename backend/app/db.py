from sqlalchemy import select

from app import database
from app.models import Scan


async def create_scan(scan_id: str, repo_url: str, webhook_url: str | None) -> None:
    async with database.AsyncSessionLocal() as session:
        session.add(Scan(id=scan_id, repo_url=repo_url, webhook_url=webhook_url))
        await session.commit()


async def get_scan(scan_id: str) -> Scan | None:
    async with database.AsyncSessionLocal() as session:
        return await session.get(Scan, scan_id)


async def update_scan(scan_id: str, status: str, report: str | None = None) -> None:
    async with database.AsyncSessionLocal() as session:
        scan = await session.get(Scan, scan_id)
        if scan:
            scan.status = status
            scan.report = report
            await session.commit()


async def update_webhook_error(scan_id: str, error: str) -> None:
    async with database.AsyncSessionLocal() as session:
        scan = await session.get(Scan, scan_id)
        if scan:
            scan.webhook_error = error
            await session.commit()


async def get_stuck_scans() -> list[str]:
    """Return IDs of scans stuck at 'running' — used for startup reconciliation."""
    async with database.AsyncSessionLocal() as session:
        result = await session.execute(select(Scan.id).where(Scan.status == "running"))
        return list(result.scalars())
