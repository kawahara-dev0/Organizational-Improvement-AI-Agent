"""Admin authentication endpoint.

POST /admin/login  — verify ADMIN_PASSWORD, return a short-lived JWT.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.auth.deps import create_admin_token
from app.settings import settings

router = APIRouter(prefix="/admin", tags=["admin-auth"])
_limiter = Limiter(key_func=get_remote_address)


class LoginRequest(BaseModel):
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/login", response_model=LoginResponse)
@_limiter.limit(lambda: settings.admin_login_rate_limit)
async def admin_login(request: Request, body: LoginRequest) -> LoginResponse:  # noqa: ARG001
    """Verify the admin password and return a JWT access token."""
    if not secrets.compare_digest(body.password, settings.admin_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect admin password.",
        )
    return LoginResponse(access_token=create_admin_token())
