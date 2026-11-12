"""
Auth schemas — Gate 6.

Pydantic models for authentication request/response bodies.
"""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # access token lifetime in seconds


class ServiceTokenResponse(BaseModel):
    """OAuth2 client-credentials response for the Orchestrate tool identity."""

    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    scope: str = "tools:read"


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=1)


class UserInfo(BaseModel):
    """Minimal caller identity returned by GET /api/v1/auth/me."""

    id: str
    email: str
    full_name: str
    roles: list[str]
    is_active: bool
