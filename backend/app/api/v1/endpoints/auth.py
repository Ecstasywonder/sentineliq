"""
Authentication endpoints — Gate 6.

Routes:
    POST /api/v1/auth/token    Login — issue access + refresh tokens
    POST /api/v1/auth/service-token  OAuth2 client-credentials service token
    POST /api/v1/auth/refresh  Exchange refresh token for new access token
    POST /api/v1/auth/logout   Revoke the presented refresh-token family
    GET  /api/v1/auth/me       Return current user identity
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Form, HTTPException, Response, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_db
from app.models.refresh_token import RefreshToken, RefreshTokenFamily
from app.models.user import Role, User, UserRole
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    ServiceTokenResponse,
    TokenResponse,
    UserInfo,
)
from app.security.dependencies import CurrentUser
from app.security.passwords import verify_password_or_dummy
from app.security.rbac import SERVICE_PURPOSE_POLICIES
from app.security.tokens import (
    TokenError,
    create_access_token,
    create_service_access_token,
    decode_refresh_token_claims,
    issue_refresh_token,
)

logger = structlog.get_logger(__name__)
router = APIRouter()
_service_basic = HTTPBasic(auto_error=False)


def _token_hash(token: str) -> str:
    """Return a non-reversible binding for a refresh JWT."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _as_utc(value: datetime) -> datetime:
    """Normalise SQLite-naive and PostgreSQL-aware timestamps."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def _load_user_roles(session: AsyncSession, user_id: str) -> list[str]:
    stmt = (
        select(Role.name)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


def _oauth_error(
    status_code: int,
    error: str,
    description: str,
    *,
    authenticate: bool = False,
) -> HTTPException:
    headers = {"Cache-Control": "no-store", "Pragma": "no-cache"}
    if authenticate:
        headers["WWW-Authenticate"] = 'Basic realm="sentineliq-orchestrate-tools"'
    return HTTPException(
        status_code=status_code,
        detail={"error": error, "error_description": description},
        headers=headers,
    )


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

    password_valid = verify_password_or_dummy(
        body.password,
        user.hashed_password if user is not None else None,
    )
    if user is None or not password_valid:
        raise _401

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "ACCOUNT_DISABLED", "message": "Account is disabled."},
        )
    if user.service_purpose is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "SERVICE_ACCOUNT_LOGIN_DISABLED",
                "message": "Service identities cannot use password login.",
            },
        )

    roles = await _load_user_roles(session, user.id)
    s = get_settings()

    access_token = create_access_token(user.id, roles)
    refresh_token, refresh_claims = issue_refresh_token(user.id)
    session.add(
        RefreshTokenFamily(
            family_id=refresh_claims.family_id,
            user_id=user.id,
        )
    )
    session.add(
        RefreshToken(
            token_id=refresh_claims.token_id,
            family_id=refresh_claims.family_id,
            user_id=user.id,
            token_hash=_token_hash(refresh_token),
            expires_at=refresh_claims.expires_at,
        )
    )

    logger.info("auth.login", user_id=user.id, roles=roles)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=s.access_token_expire_minutes * 60,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/auth/service-token — OAuth2 client credentials
# ---------------------------------------------------------------------------


@router.post(
    "/service-token",
    response_model=ServiceTokenResponse,
    summary="Issue a purpose-bound Orchestrate tools token",
    status_code=200,
)
async def service_token(
    response: Response,
    grant_type: Annotated[str, Form()],
    scope: Annotated[str | None, Form()] = None,
    credentials: Annotated[HTTPBasicCredentials | None, Depends(_service_basic)] = None,
    session: AsyncSession = Depends(get_db),
) -> ServiceTokenResponse:
    """Implement OAuth2 client credentials for the Orchestrate team connection.

    The configured client secret authenticates only the token request. Issued
    JWTs remain short-lived and are additionally restricted by audience,
    purpose, the active service identity, and its database role.
    """
    if grant_type != "client_credentials":
        raise _oauth_error(400, "unsupported_grant_type", "grant_type must be client_credentials")

    requested_scopes = set(scope.split()) if scope else {"tools:read"}
    if requested_scopes != {"tools:read"}:
        raise _oauth_error(400, "invalid_scope", "Only the tools:read scope is available")

    settings = get_settings()
    expected_id = settings.orchestrate_tools_client_id
    expected_secret = settings.orchestrate_tools_client_secret.get_secret_value()
    if not settings.orchestrate_tools_oauth_configured:
        logger.error("auth.service_token_unconfigured")
        raise _oauth_error(503, "temporarily_unavailable", "Service authentication unavailable")

    provided_id = credentials.username if credentials is not None else ""
    provided_secret = credentials.password if credentials is not None else ""
    id_matches = secrets.compare_digest(provided_id.encode(), expected_id.encode())
    secret_matches = secrets.compare_digest(provided_secret.encode(), expected_secret.encode())
    if credentials is None or not (id_matches and secret_matches):
        raise _oauth_error(
            401,
            "invalid_client",
            "Client authentication failed",
            authenticate=True,
        )

    result = await session.execute(
        select(User).where(
            User.service_purpose == "orchestrate_tools",
            User.is_active.is_(True),
        )
    )
    service_users = list(result.scalars().all())
    if len(service_users) != 1:
        logger.error("auth.service_identity_unavailable", purpose="orchestrate_tools")
        raise _oauth_error(503, "temporarily_unavailable", "Service identity unavailable")

    service_user = service_users[0]
    roles = await _load_user_roles(session, service_user.id)
    required_role, allowed_permissions = SERVICE_PURPOSE_POLICIES["orchestrate_tools"]
    if set(roles) != {required_role} or allowed_permissions != frozenset({"tools:read"}):
        logger.error(
            "auth.service_identity_role_invalid",
            user_id=service_user.id,
            purpose="orchestrate_tools",
        )
        raise _oauth_error(503, "temporarily_unavailable", "Service identity unavailable")

    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    logger.info("auth.service_token_issued", user_id=service_user.id, scope="tools:read")
    return ServiceTokenResponse(
        access_token=create_service_access_token(
            service_user.id,
            [required_role],
            "orchestrate_tools",
        ),
        expires_in=settings.access_token_expire_minutes * 60,
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
        claims = decode_refresh_token_claims(body.refresh_token)
    except TokenError:
        raise _401 from None

    # Every generation in a login session first locks the same family row.
    # This prevents a descendant rotation from racing a replay revocation.
    family_result = await session.execute(
        select(RefreshTokenFamily)
        .where(RefreshTokenFamily.family_id == claims.family_id)
        .with_for_update()
    )
    family = family_result.scalar_one_or_none()
    if family is None or family.user_id != claims.user_id:
        raise _401

    token_result = await session.execute(
        select(RefreshToken).where(RefreshToken.token_id == claims.token_id).with_for_update()
    )
    stored = token_result.scalar_one_or_none()
    now = datetime.now(UTC)

    if stored is None or stored.token_hash != _token_hash(body.refresh_token):
        raise _401

    replayed = (
        family.revoked_at is not None or stored.used_at is not None or stored.revoked_at is not None
    )
    expired = _as_utc(stored.expires_at) <= now
    family_mismatch = stored.family_id != claims.family_id or stored.user_id != claims.user_id
    if replayed or expired or family_mismatch:
        # Persist family revocation before returning 401; allowing the request
        # dependency to roll back would silently defeat replay containment.
        family.revoked_at = now
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == stored.family_id)
            .values(revoked_at=now)
        )
        await session.commit()
        logger.warning(
            "auth.refresh_replay_rejected",
            user_id=stored.user_id,
            family_id=stored.family_id,
            token_id=stored.token_id,
        )
        raise _401

    user: User | None = await session.get(User, claims.user_id)
    if user is None or not user.is_active or user.service_purpose is not None:
        family.revoked_at = now
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == stored.family_id)
            .values(revoked_at=now)
        )
        await session.commit()
        raise _401

    roles = await _load_user_roles(session, user.id)
    s = get_settings()

    access_token = create_access_token(user.id, roles)
    new_refresh_token, new_claims = issue_refresh_token(
        user.id,
        family_id=stored.family_id,
    )
    stored.used_at = now
    stored.replaced_by_token_id = new_claims.token_id
    session.add(
        RefreshToken(
            token_id=new_claims.token_id,
            family_id=new_claims.family_id,
            user_id=user.id,
            token_hash=_token_hash(new_refresh_token),
            expires_at=new_claims.expires_at,
        )
    )

    logger.info(
        "auth.refresh_rotated",
        user_id=user.id,
        family_id=stored.family_id,
        old_token_id=stored.token_id,
        new_token_id=new_claims.token_id,
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        expires_in=s.access_token_expire_minutes * 60,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/auth/logout
# ---------------------------------------------------------------------------


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke the presented refresh-token family",
)
async def logout(
    body: RefreshRequest,
    session: AsyncSession = Depends(get_db),
) -> None:
    """Revoke every refresh token in a login family.

    The response deliberately does not reveal whether the token was malformed,
    expired, issued by this service, or already revoked.  A caller can safely
    retry logout, while a valid token from an earlier rotation still revokes its
    active descendant.
    """
    try:
        claims = decode_refresh_token_claims(body.refresh_token)
    except TokenError:
        return

    family_result = await session.execute(
        select(RefreshTokenFamily)
        .where(RefreshTokenFamily.family_id == claims.family_id)
        .with_for_update()
    )
    family = family_result.scalar_one_or_none()
    if family is None or family.user_id != claims.user_id:
        return

    token_result = await session.execute(
        select(RefreshToken).where(RefreshToken.token_id == claims.token_id)
    )
    stored = token_result.scalar_one_or_none()
    if (
        stored is None
        or stored.family_id != family.family_id
        or stored.user_id != claims.user_id
        or stored.token_hash != _token_hash(body.refresh_token)
    ):
        return

    # Preserve the first revocation timestamp so repeated logout calls are
    # idempotent, including when the client retries after a lost response.
    if family.revoked_at is None:
        now = datetime.now(UTC)
        family.revoked_at = now
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family.family_id)
            .where(RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        await session.commit()
        logger.info("auth.logout", user_id=family.user_id, family_id=family.family_id)


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
