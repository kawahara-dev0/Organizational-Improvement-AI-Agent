"""Admin authentication endpoint.

POST /admin/login  — verify ADMIN_PASSWORD, return a short-lived JWT.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.auth.deps import create_admin_token
from app.settings import settings

router = APIRouter(prefix="/admin", tags=["admin-auth"])


class LoginRequest(BaseModel):
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/login", response_model=LoginResponse)
async def admin_login(body: LoginRequest) -> LoginResponse:
    """Verify the admin password and return a JWT access token."""
    if not secrets.compare_digest(body.password, settings.admin_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect admin password.",
        )
    return LoginResponse(access_token=create_admin_token())
