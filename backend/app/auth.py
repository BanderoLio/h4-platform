from fastapi import Request, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.config import settings

_scheme = HTTPBearer()


async def require_api_key(request: Request) -> None:
    credentials: HTTPAuthorizationCredentials | None = await _scheme(request)
    if credentials is None or credentials.credentials != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
