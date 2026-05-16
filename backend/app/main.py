from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from app.routes.scan import router as scan_router


# def _run_migrations() -> None:
#     cfg = Config("alembic.ini")
#     command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ARQ queue bootstrap is intentionally disabled:
    # /scan endpoints now delegate execution to agentsec.session.
    # Legacy worker code remains in the repo as migration fallback only.
    yield


app = FastAPI(title="Hack4 Pentest API", lifespan=lifespan)
app.include_router(scan_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


def _custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
    schema.setdefault("components", {}).setdefault("securitySchemes", {})["BearerAuth"] = {
        "type": "http",
        "scheme": "bearer",
    }
    for path in schema.get("paths", {}).values():
        for operation in path.values():
            operation.setdefault("security", [{"BearerAuth": []}])
    app.openapi_schema = schema
    return schema


app.openapi = _custom_openapi
