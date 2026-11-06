"""
JWT token issuance and verification — Gate 6.

Issues short-lived access tokens and longer-lived refresh tokens.
Claims are minimal: sub (user id), roles, exp, type, plus refresh-token jti
and family identifiers needed for one-time rotation.

Design notes:
- Access token lifetime:  settings.access_token_expire_minutes  (default 60)
- Refresh token lifetime: settings.refresh_token_expire_days    (default 7)
- Algorithm: HS256 (settings.algorithm)
- Secret:    settings.secret_key  — MUST be set in production
- Token type claim ("type": "access" | "refresh") prevents refresh tokens
  being used as access tokens and vice versa.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt

from app.config import get_settings


class TokenError(ValueError):
    """Raised when a token cannot be decoded or is invalid."""


def _settings():
    return get_settings()


def create_access_token(user_id: str, roles: list[str]) -> str:
    """Issue a signed JWT access token."""
    s = _settings()
    expire = datetime.now(UTC) + timedelta(minutes=s.access_token_expire_minutes)
    payload = {
        "sub": user_id,
        "roles": roles,
        "type": "access",
        "exp": expire,
    }
    return jwt.encode(payload, s.secret_key, algorithm=s.algorithm)


@dataclass(frozen=True, slots=True)
class RefreshTokenClaims:
    """Validated server-side identity for a refresh token."""

    user_id: str
    token_id: str
    family_id: str
    expires_at: datetime


def issue_refresh_token(
    user_id: str,
    *,
    family_id: str | None = None,
) -> tuple[str, RefreshTokenClaims]:
    """Issue a refresh token with a unique ID and rotation-family ID.

    Callers must persist the returned claims before returning the token to a
    client.  A signed token that has no matching database record is rejected by
    the refresh endpoint.
    """
    s = _settings()
    expire = datetime.now(UTC) + timedelta(days=s.refresh_token_expire_days)
    token_id = str(uuid.uuid4())
    resolved_family_id = family_id or str(uuid.uuid4())
    payload = {
        "sub": user_id,
        "type": "refresh",
        "jti": token_id,
        "family": resolved_family_id,
        "exp": expire,
    }
    token = jwt.encode(payload, s.secret_key, algorithm=s.algorithm)
    return token, RefreshTokenClaims(
        user_id=user_id,
        token_id=token_id,
        family_id=resolved_family_id,
        expires_at=expire,
    )


def create_refresh_token(user_id: str) -> str:
    """Issue a signed refresh JWT.

    This compatibility helper is useful for token-format tests.  Application
    endpoints use :func:`issue_refresh_token` and persist the returned claims.
    """
    token, _ = issue_refresh_token(user_id)
    return token


def decode_access_token(token: str) -> dict:
    """
    Decode and validate an access token.

    Returns the payload dict on success.
    Raises TokenError on any failure (expired, tampered, wrong type).
    """
    s = _settings()
    try:
        payload = jwt.decode(token, s.secret_key, algorithms=[s.algorithm])
    except JWTError as exc:
        raise TokenError(f"Invalid token: {exc}") from exc

    if payload.get("type") != "access":
        raise TokenError("Token is not an access token.")
    return payload


def decode_refresh_token_claims(token: str) -> RefreshTokenClaims:
    """
    Decode and validate a refresh token.

    Returns the subject, token ID, family ID, and expiry on success.
    Raises TokenError on any failure.
    """
    s = _settings()
    try:
        payload = jwt.decode(token, s.secret_key, algorithms=[s.algorithm])
    except JWTError as exc:
        raise TokenError(f"Invalid refresh token: {exc}") from exc

    if payload.get("type") != "refresh":
        raise TokenError("Token is not a refresh token.")

    user_id: str | None = payload.get("sub")
    if not user_id:
        raise TokenError("Refresh token missing subject.")

    token_id = payload.get("jti")
    family_id = payload.get("family")
    expires_at = payload.get("exp")
    if not isinstance(token_id, str) or not token_id:
        raise TokenError("Refresh token missing token ID.")
    if not isinstance(family_id, str) or not family_id:
        raise TokenError("Refresh token missing family ID.")
    if not isinstance(expires_at, (int, float)):
        raise TokenError("Refresh token missing expiry.")

    return RefreshTokenClaims(
        user_id=user_id,
        token_id=token_id,
        family_id=family_id,
        expires_at=datetime.fromtimestamp(expires_at, tz=UTC),
    )


def decode_refresh_token(token: str) -> str:
    """Decode a refresh token and return its subject for compatibility."""
    return decode_refresh_token_claims(token).user_id
