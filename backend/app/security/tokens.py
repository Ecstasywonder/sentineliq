"""
JWT token issuance and verification — Gate 6.

Issues short-lived access tokens and longer-lived refresh tokens.
All claims are minimal: sub (user id), roles, exp, type.

Design notes:
- Access token lifetime:  settings.access_token_expire_minutes  (default 60)
- Refresh token lifetime: settings.refresh_token_expire_days    (default 7)
- Algorithm: HS256 (settings.algorithm)
- Secret:    settings.secret_key  — MUST be set in production
- Token type claim ("type": "access" | "refresh") prevents refresh tokens
  being used as access tokens and vice versa.
"""

from __future__ import annotations

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


def create_refresh_token(user_id: str) -> str:
    """Issue a signed JWT refresh token (no roles — roles re-fetched on refresh)."""
    s = _settings()
    expire = datetime.now(UTC) + timedelta(days=s.refresh_token_expire_days)
    payload = {
        "sub": user_id,
        "type": "refresh",
        "exp": expire,
    }
    return jwt.encode(payload, s.secret_key, algorithm=s.algorithm)


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


def decode_refresh_token(token: str) -> str:
    """
    Decode and validate a refresh token.

    Returns the user_id (sub) on success.
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
    return user_id
