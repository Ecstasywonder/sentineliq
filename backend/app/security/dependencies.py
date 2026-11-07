"""
FastAPI auth dependencies — Gate 6.

Provides:
  get_current_user  -- decodes Bearer token, loads User from DB
  CurrentUser       -- type alias for Annotated dependency
  require_permission(perm) -- factory that returns a guard dependency
"""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.user import Role, User, UserRole
from app.security.rbac import has_permission, service_purpose_allows
from app.security.tokens import TokenError, decode_access_token

logger = structlog.get_logger(__name__)

_bearer = HTTPBearer(auto_error=True)


# ---------------------------------------------------------------------------
# Token extraction dataclass
# ---------------------------------------------------------------------------


class AuthenticatedUser:
    """Lightweight identity object attached to each authenticated request."""

    def __init__(self, user: User, roles: list[str], service_purpose: str | None = None) -> None:
        self.user = user
        self.id = user.id
        self.email = user.email
        self.full_name = user.full_name
        self.roles = roles
        self.is_active = user.is_active
        self.service_purpose = service_purpose


# ---------------------------------------------------------------------------
# Core dependency
# ---------------------------------------------------------------------------


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    session: AsyncSession = Depends(get_db),
) -> AuthenticatedUser:
    """
    FastAPI dependency — decode Bearer token, load user + roles from DB.

    Raises HTTP 401 on any auth failure.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "UNAUTHORIZED", "message": "Invalid or expired token."},
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_access_token(credentials.credentials)
    except TokenError:
        raise credentials_exception from None

    user_id: str | None = payload.get("sub")
    if not user_id:
        raise credentials_exception

    # Load user
    user: User | None = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise credentials_exception

    token_purpose = payload.get("purpose")
    if token_purpose != user.service_purpose:
        # A machine identity can never use a legacy human token, and a service
        # token cannot be rebound to an interactive user.
        raise credentials_exception

    # Load roles
    stmt = (
        select(Role.name)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
    )
    result = await session.execute(stmt)
    roles: list[str] = list(result.scalars().all())

    return AuthenticatedUser(user=user, roles=roles, service_purpose=token_purpose)


async def get_current_human_user(
    auth: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    """Reject purpose-bound service tokens on explicitly human endpoints."""
    if auth.service_purpose is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "HUMAN_TOKEN_REQUIRED", "message": "Interactive user token required."},
        )
    return auth


# Convenience type alias for route signatures
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_human_user)]


# ---------------------------------------------------------------------------
# Permission guard factory
# ---------------------------------------------------------------------------


def require_permission(permission: str):
    """
    Return a FastAPI dependency that enforces *permission*.

    Usage:
        @router.get("/", dependencies=[Depends(require_permission("events:read"))])
    Or as a parameter:
        async def route(auth: CurrentUser = Depends(require_permission("events:read"))):
    """

    async def _guard(auth: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
        if auth.service_purpose is not None and not service_purpose_allows(
            auth.service_purpose, auth.roles, permission
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "SERVICE_PURPOSE_FORBIDDEN",
                    "message": "Service token purpose does not permit this operation.",
                },
            )
        if not has_permission(auth.roles, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "FORBIDDEN",
                    "message": f"Permission '{permission}' required.",
                },
            )
        return auth

    return _guard
