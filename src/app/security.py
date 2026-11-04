import hmac

from fastapi import Header, HTTPException

from app.config import settings


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = settings.api_key.get_secret_value().encode("utf-8")
    supplied = (x_api_key or "").encode("utf-8")
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
