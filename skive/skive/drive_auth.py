"""Supabase Auth boundary for the new, user-scoped drive API."""

import os
from functools import lru_cache
from uuid import UUID

import httpx
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from skive.config import load_environment

load_environment()
bearer = HTTPBearer(auto_error=False)


@lru_cache
def public_config() -> dict[str, str]:
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_PUBLISHABLE_KEY", "") or os.getenv("SUPABASE_ANON_KEY", "")
    if not url.startswith("https://") or not key:
        raise HTTPException(503, "SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY are not configured")
    return {"url": url, "key": key, "bucket": "skive-originals"}


def current_user_id(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> UUID:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(401, "Login required")
    cfg = public_config()
    try:
        response = httpx.get(
            f"{cfg['url']}/auth/v1/user",
            headers={"apikey": cfg["key"], "Authorization": f"Bearer {credentials.credentials}"},
            timeout=8,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (401, 403):
            raise HTTPException(401, "Invalid or expired session") from exc
        raise HTTPException(503, "Supabase Auth is unavailable") from exc
    except httpx.RequestError as exc:
        raise HTTPException(503, "Supabase Auth is unavailable") from exc
    try:
        return UUID(response.json()["id"])
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(401, "Invalid or expired session") from exc
