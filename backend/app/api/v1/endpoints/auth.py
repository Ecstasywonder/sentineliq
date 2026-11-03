"""
Authentication endpoints — Gate 6.

Routes:
    POST /api/v1/auth/token    Login — issue access + refresh tokens
    POST /api/v1/auth/refresh  Exchange refresh token for new access token
    GET  /api/v1/auth/me       Return current user identity
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_db
from app.models.user import Role, User, UserRole
from app.schemas.auth import LoginRequest, RefreshRequest, TokenResponse, UserInfo
from app.security.dependencies import CurrentUser
from app.security.passwords import verify_password
from app.security.tokens import TokenError, create_access_token, create_refresh_token, decode_refresh_token

logger = structlog.get_logger(__name__)
router = APIRouter()


async def _load_user_roles(session: AsyncSession, user_id: str) -> list[str]:
    stmt = (
        select(Role.name)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# POST /api/v1/auth/token — login
# ---------------------------------------------------------------------------


@router.post(
    "/token",
    response_model=TokenResponse,
    summary="Login and obtain JWT tokens",
    status_code=200,
)
async def login(
    body: LoginRequest,
    session: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """
    Authenticate with email + password. Returns access and refresh tokens.
    Returns HTTP 401 for any credential failure (email not found OR wrong password)
    — deliberately no distinction to prevent user enumeration.
    """
    _401 = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "INVALID_CREDENTIALS", "message": "Invalid email or password."},
        headers={"WWW-Authenticate": "Bearer"},
    )

    stmt = select(User).where(User.email == body.email.lower())
    result = await session.execute(stmt)
    user: User | None = result.scalar_one_or_none()

    if user is None or not verify_password(body.password, user.hashed_password):
        raise _401

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "ACCOUNT_DISABLED", "message": "Account is disabled."},
        )

    roles = await _load_user_roles(session, user.id)
    s = get_settings()

    access_token = create_access_token(user.id, roles)
    refresh_token = create_refresh_token(user.id)

    logger.info("auth.login", user_id=user.id, roles=roles)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=s.access_token_expire_minutes * 60,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/auth/refresh
# ---------------------------------------------------------------------------


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh access token",
    status_code=200,
)
async def refresh(
    body: RefreshRequest,
    session: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Exchange a valid refresh token for a new access token + new refresh token."""
    _401 = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "INVALID_TOKEN", "message": "Invalid or expired refresh token."},
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        user_id = decode_refresh_token(body.refresh_token)
    except TokenError:
        raise _401

    user: User | None = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise _401

    roles = await _load_user_roles(session, user.id)
    s = get_settings()

    access_token = create_access_token(user.id, roles)
    new_refresh_token = create_refresh_token(user.id)

    logger.info("auth.refresh", user_id=user.id)

    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        expires_in=s.access_token_expire_minutes * 60,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/auth/me
# ---------------------------------------------------------------------------


@router.get(
    "/me",
    response_model=UserInfo,
    summary="Return current authenticated user",
)
async def me(auth: CurrentUser) -> UserInfo:
    """Return the identity of the currently authenticated caller."""
    return UserInfo(
        id=auth.id,
        email=auth.email,
        full_name=auth.full_name,
        roles=auth.roles,
        is_active=auth.is_active,
    )
