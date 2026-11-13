"""
Auth & RBAC tests -- Gate 6.

Tests cover:
- Password hashing and verification
- JWT access/refresh token issuance and decoding
- Token type enforcement (access token rejected as refresh and vice versa)
- Expired token rejection
- POST /api/v1/auth/token: happy path, wrong password, unknown email, disabled account
- POST /api/v1/auth/refresh: valid refresh, invalid token
- GET /api/v1/auth/me: returns caller identity
- RBAC permission model: role -> permission mappings
- require_permission guard: 403 for insufficient role
- Events endpoints: 401 without auth, 403 with insufficient role
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.auth import logout as logout_endpoint
from app.api.v1.endpoints.auth import refresh as refresh_endpoint
from app.config import get_settings
from app.db.session import get_db
from app.main import app
from app.models.refresh_token import RefreshToken, RefreshTokenFamily
from app.models.user import Role, User, UserRole
from app.schemas.auth import RefreshRequest
from app.security.dependencies import AuthenticatedUser, get_current_user
from app.security.passwords import hash_password, verify_password, verify_password_or_dummy
from app.security.rbac import has_permission, permissions_for_roles
from app.security.tokens import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    decode_refresh_token_claims,
)


def _id() -> str:
    return str(uuid.uuid4())


# ===========================================================================
# Password utilities (pure -- no DB)
# ===========================================================================


class TestPasswords:
    def test_hash_is_not_plaintext(self):
        h = hash_password("secret")
        assert h != "secret"
        assert h.startswith("$2b$")

    def test_verify_correct_password(self):
        h = hash_password("correct-horse")
        assert verify_password("correct-horse", h) is True

    def test_verify_wrong_password(self):
        h = hash_password("correct-horse")
        assert verify_password("wrong-horse", h) is False

    def test_two_hashes_differ(self):
        """bcrypt uses random salt per hash."""
        assert hash_password("same") != hash_password("same")

    def test_unknown_user_still_uses_dummy_bcrypt(self):
        assert verify_password_or_dummy("any-password", None) is False


# ===========================================================================
# JWT tokens (pure -- no DB)
# ===========================================================================


class TestTokens:
    def test_access_token_decodes(self):
        payload = decode_access_token(create_access_token("user-1", ["officer"]))
        assert payload["sub"] == "user-1"
        assert "officer" in payload["roles"]
        assert payload["type"] == "access"

    def test_refresh_token_decodes(self):
        user_id = decode_refresh_token(create_refresh_token("user-2"))
        assert user_id == "user-2"

    def test_access_token_rejected_as_refresh(self):
        token = create_access_token("u", ["officer"])
        with pytest.raises(TokenError, match="not a refresh token"):
            decode_refresh_token(token)

    def test_refresh_token_rejected_as_access(self):
        token = create_refresh_token("u")
        with pytest.raises(TokenError, match="not an access token"):
            decode_access_token(token)

    def test_tampered_token_raises(self):
        token = create_access_token("u", [])
        with pytest.raises(TokenError):
            decode_access_token(token + "x")

    def test_expired_token_raises(self):
        s = get_settings()
        payload = {
            "sub": "u",
            "roles": [],
            "type": "access",
            "exp": datetime.now(UTC) - timedelta(seconds=1),
        }
        expired = jwt.encode(payload, s.secret_key, algorithm=s.algorithm)
        with pytest.raises(TokenError):
            decode_access_token(expired)

    def test_access_token_contains_roles(self):
        roles = ["officer", "supervisor"]
        token = create_access_token("u", roles)
        payload = decode_access_token(token)
        assert set(payload["roles"]) == set(roles)

    def test_refresh_token_has_no_roles(self):
        token = create_refresh_token("u")
        s = get_settings()
        payload = jwt.decode(token, s.secret_key, algorithms=[s.algorithm])
        assert "roles" not in payload


# ===========================================================================
# RBAC permission model (pure -- no DB)
# ===========================================================================


class TestRbac:
    def test_officer_can_read_events(self):
        assert has_permission(["officer"], "events:read")

    def test_officer_can_decide(self):
        assert has_permission(["officer"], "events:decide")

    def test_officer_cannot_override(self):
        assert not has_permission(["officer"], "events:override")

    def test_officer_cannot_admin_users(self):
        assert not has_permission(["officer"], "admin:users")

    def test_supervisor_can_override(self):
        assert has_permission(["supervisor"], "events:override")

    def test_platform_admin_has_all(self):
        perms = permissions_for_roles(["platform_admin"])
        for p in [
            "events:read",
            "events:ingest",
            "events:decide",
            "events:override",
            "audit:read",
            "admin:users",
            "admin:policy",
            "admin:agents",
        ]:
            assert p in perms, f"platform_admin missing {p}"

    def test_audit_reviewer_read_only(self):
        perms = permissions_for_roles(["audit_reviewer"])
        assert "events:read" in perms
        assert "audit:read" in perms
        assert "events:decide" not in perms
        assert "events:ingest" not in perms

    def test_multiple_roles_union(self):
        """User with officer + audit_reviewer gets union of both."""
        perms = permissions_for_roles(["officer", "audit_reviewer"])
        assert "events:read" in perms
        assert "audit:read" in perms
        assert "events:decide" in perms

    def test_unknown_role_grants_nothing(self):
        assert permissions_for_roles(["completely_unknown"]) == frozenset()

    def test_empty_roles_grants_nothing(self):
        assert not has_permission([], "events:read")


# ===========================================================================
# Auth endpoint tests (HTTP -- uses client fixture with stub auth bypassed)
# ===========================================================================


async def _seed_user(
    session: AsyncSession,
    email: str,
    password: str,
    role_name: str = "officer",
    is_active: bool = True,
) -> User:
    """Create a User + Role + UserRole in the test DB."""
    role_id = _id()
    role = Role(id=role_id, name=f"{role_name}_{_id()[:6]}", description=role_name)
    session.add(role)
    await session.flush()

    user = User(
        id=_id(),
        email=email,
        full_name="Test Person",
        hashed_password=hash_password(password),
        is_active=is_active,
        is_verified=True,
    )
    session.add(user)
    await session.flush()

    session.add(UserRole(id=_id(), user_id=user.id, role_id=role.id))
    await session.flush()
    return user


@asynccontextmanager
async def _auth_client(db_session: AsyncSession):
    """
    Context manager: a raw AsyncClient with only the DB overridden.
    No stub auth — used to test real auth routes (login, refresh).
    """

    async def _override_db() -> AsyncGenerator:
        yield db_session

    previous_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _override_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        if previous_override is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous_override


@pytest.mark.asyncio
async def test_login_happy_path(db_session: AsyncSession) -> None:
    """Correct credentials return access + refresh tokens."""
    email = f"auth_happy_{_id()[:8]}@test.com"
    await _seed_user(db_session, email, "goodpassword")
    await db_session.commit()

    async with _auth_client(db_session) as ac:
        resp = await ac.post(
            "/api/v1/auth/token",
            json={"email": email, "password": "goodpassword"},
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0


@pytest.mark.asyncio
async def test_login_persists_refresh_token_family_before_its_token(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Login flushes the FK parent before staging the refresh-token child."""
    email = f"auth_refresh_order_{_id()[:8]}@test.com"
    await _seed_user(db_session, email, "pass")
    await db_session.commit()

    original_flush = db_session.flush
    flush_calls: list[tuple[bool, bool]] = []

    async def tracked_flush(*args, **kwargs) -> None:
        pending = list(db_session.new)
        flush_calls.append(
            (
                any(isinstance(item, RefreshTokenFamily) for item in pending),
                any(isinstance(item, RefreshToken) for item in pending),
            )
        )
        await original_flush(*args, **kwargs)

    monkeypatch.setattr(db_session, "flush", tracked_flush)

    async with _auth_client(db_session) as ac:
        response = await ac.post(
            "/api/v1/auth/token",
            json={"email": email, "password": "pass"},
        )

    assert response.status_code == 200, response.text
    assert flush_calls == [(True, False), (False, True)]

    claims = decode_refresh_token_claims(response.json()["refresh_token"])
    await db_session.commit()
    family = await db_session.get(RefreshTokenFamily, claims.family_id)
    token = await db_session.get(RefreshToken, claims.token_id)
    assert family is not None
    assert token is not None
    assert token.family_id == family.family_id


@pytest.mark.asyncio
async def test_login_wrong_password(db_session: AsyncSession) -> None:
    """Wrong password returns 401."""
    email = f"auth_wrong_{_id()[:8]}@test.com"
    await _seed_user(db_session, email, "rightpass")
    await db_session.commit()

    async with _auth_client(db_session) as ac:
        resp = await ac.post(
            "/api/v1/auth/token",
            json={"email": email, "password": "wrongpass"},
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "INVALID_CREDENTIALS"


@pytest.mark.asyncio
async def test_login_unknown_email(db_session: AsyncSession) -> None:
    """Unknown email returns 401 (not 404 -- prevents user enumeration)."""
    async with _auth_client(db_session) as ac:
        resp = await ac.post(
            "/api/v1/auth/token",
            json={"email": "nobody@nowhere.com", "password": "pass"},
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_disabled_account(db_session: AsyncSession) -> None:
    """Disabled account returns 403."""
    email = f"auth_disabled_{_id()[:8]}@test.com"
    await _seed_user(db_session, email, "pass", is_active=False)
    await db_session.commit()

    async with _auth_client(db_session) as ac:
        resp = await ac.post(
            "/api/v1/auth/token",
            json={"email": email, "password": "pass"},
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "ACCOUNT_DISABLED"


@pytest.mark.asyncio
async def test_refresh_token_issues_new_access(db_session: AsyncSession) -> None:
    """A refresh token issued by login rotates to a new one exactly once."""
    email = f"auth_refresh_{_id()[:8]}@test.com"
    await _seed_user(db_session, email, "pass")
    await db_session.commit()

    async with _auth_client(db_session) as ac:
        login_resp = await ac.post(
            "/api/v1/auth/token",
            json={"email": email, "password": "pass"},
        )
        assert login_resp.status_code == 200
        refresh = login_resp.json()["refresh_token"]

        resp = await ac.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh},
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert "access_token" in resp.json()
    assert resp.json()["refresh_token"] != refresh


@pytest.mark.asyncio
async def test_refresh_token_replay_revokes_token_family(db_session: AsyncSession) -> None:
    """Reusing a rotated token revokes the descendant issued from it."""
    email = f"auth_replay_{_id()[:8]}@test.com"
    await _seed_user(db_session, email, "pass")
    await db_session.commit()

    async with _auth_client(db_session) as ac:
        login_resp = await ac.post(
            "/api/v1/auth/token",
            json={"email": email, "password": "pass"},
        )
        original = login_resp.json()["refresh_token"]

        first_rotation = await ac.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": original},
        )
        assert first_rotation.status_code == 200
        descendant = first_rotation.json()["refresh_token"]

        replay = await ac.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": original},
        )
        descendant_after_replay = await ac.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": descendant},
        )

    app.dependency_overrides.clear()
    assert replay.status_code == 401
    assert descendant_after_replay.status_code == 401


@pytest.mark.asyncio
async def test_logout_revokes_the_entire_refresh_token_family(
    db_session: AsyncSession,
) -> None:
    """Logout with a rotated token invalidates its active descendant too."""
    email = f"auth_logout_{_id()[:8]}@test.com"
    await _seed_user(db_session, email, "pass")
    await db_session.commit()

    async with _auth_client(db_session) as ac:
        login_response = await ac.post(
            "/api/v1/auth/token",
            json={"email": email, "password": "pass"},
        )
        assert login_response.status_code == 200, login_response.text
        original = login_response.json()["refresh_token"]
        refresh_response = await ac.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": original},
        )
        descendant = refresh_response.json()["refresh_token"]

        logout_response = await ac.post(
            "/api/v1/auth/logout",
            json={"refresh_token": original},
        )
        descendant_after_logout = await ac.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": descendant},
        )

    app.dependency_overrides.clear()
    assert logout_response.status_code == 204
    assert descendant_after_logout.status_code == 401


@pytest.mark.asyncio
async def test_logout_is_idempotent_and_does_not_enumerate_tokens(
    db_session: AsyncSession,
) -> None:
    """Known, repeated, and malformed tokens all receive the same response."""
    email = f"auth_logout_idempotent_{_id()[:8]}@test.com"
    await _seed_user(db_session, email, "pass")
    await db_session.commit()

    async with _auth_client(db_session) as ac:
        login_response = await ac.post(
            "/api/v1/auth/token",
            json={"email": email, "password": "pass"},
        )
        refresh = login_response.json()["refresh_token"]
        first = await ac.post("/api/v1/auth/logout", json={"refresh_token": refresh})

        claims = decode_refresh_token_claims(refresh)
        family = await db_session.scalar(
            select(RefreshTokenFamily).where(
                RefreshTokenFamily.family_id == claims.family_id,
            )
        )
        assert family is not None
        first_revoked_at = family.revoked_at
        tokens = list(
            (
                await db_session.scalars(
                    select(RefreshToken).where(RefreshToken.family_id == claims.family_id),
                )
            ).all()
        )
        assert tokens
        assert all(token.revoked_at == first_revoked_at for token in tokens)

        repeated = await ac.post("/api/v1/auth/logout", json={"refresh_token": refresh})
        malformed = await ac.post(
            "/api/v1/auth/logout",
            json={"refresh_token": "not.a.refresh.token"},
        )

    app.dependency_overrides.clear()
    assert [first.status_code, repeated.status_code, malformed.status_code] == [204, 204, 204]
    await db_session.refresh(family)
    assert family.revoked_at == first_revoked_at


@pytest.mark.asyncio
async def test_unregistered_signed_refresh_token_is_rejected(
    db_session: AsyncSession,
) -> None:
    """A correctly signed JWT is unusable unless the server issued and stored it."""
    email = f"auth_unregistered_{_id()[:8]}@test.com"
    user = await _seed_user(db_session, email, "pass")
    await db_session.commit()

    refresh = create_refresh_token(user.id)
    async with _auth_client(db_session) as ac:
        resp = await ac.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh},
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_refresh_invalid_token(db_session: AsyncSession) -> None:
    """Garbage refresh token returns 401."""
    async with _auth_client(db_session) as ac:
        resp = await ac.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": "not.a.token"},
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_refresh_disabled_user_revokes_every_token_in_family(
    db_session: AsyncSession,
) -> None:
    """Disabling an account invalidates an otherwise valid login session."""
    await app.state.rate_limiter.reset()
    email = f"auth_refresh_disabled_{_id()[:8]}@test.com"
    user = await _seed_user(db_session, email, "pass")
    await db_session.commit()

    async with _auth_client(db_session) as ac:
        login_response = await ac.post(
            "/api/v1/auth/token",
            json={"email": email, "password": "pass"},
        )
        assert login_response.status_code == 200, login_response.text
        refresh = login_response.json()["refresh_token"]
        claims = decode_refresh_token_claims(refresh)

        user.is_active = False
        await db_session.commit()

        with pytest.raises(HTTPException) as exc_info:
            await refresh_endpoint(RefreshRequest(refresh_token=refresh), db_session)

    app.dependency_overrides.clear()
    assert exc_info.value.status_code == 401
    family = await db_session.scalar(
        select(RefreshTokenFamily).where(RefreshTokenFamily.family_id == claims.family_id)
    )
    tokens = list(
        (
            await db_session.scalars(
                select(RefreshToken).where(RefreshToken.family_id == claims.family_id)
            )
        ).all()
    )
    assert family is not None
    assert family.revoked_at is not None
    assert tokens
    assert all(token.revoked_at is not None for token in tokens)


@pytest.mark.asyncio
async def test_refresh_expired_stored_token_revokes_its_family(
    db_session: AsyncSession,
) -> None:
    """Server-side expiry must contain the whole family, even with a signed JWT."""
    await app.state.rate_limiter.reset()
    email = f"auth_refresh_expired_{_id()[:8]}@test.com"
    await _seed_user(db_session, email, "pass")
    await db_session.commit()

    async with _auth_client(db_session) as ac:
        login_response = await ac.post(
            "/api/v1/auth/token",
            json={"email": email, "password": "pass"},
        )
        assert login_response.status_code == 200, login_response.text
        refresh = login_response.json()["refresh_token"]
        claims = decode_refresh_token_claims(refresh)
        stored = await db_session.get(RefreshToken, claims.token_id)
        assert stored is not None
        stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db_session.commit()

        with pytest.raises(HTTPException) as exc_info:
            await refresh_endpoint(RefreshRequest(refresh_token=refresh), db_session)

    app.dependency_overrides.clear()
    assert exc_info.value.status_code == 401
    family = await db_session.scalar(
        select(RefreshTokenFamily).where(RefreshTokenFamily.family_id == claims.family_id)
    )
    assert family is not None
    assert family.revoked_at is not None


@pytest.mark.asyncio
async def test_refresh_rejects_token_when_its_family_belongs_to_another_user(
    db_session: AsyncSession,
) -> None:
    """A refresh claim cannot be rebound to another user's token family."""
    await app.state.rate_limiter.reset()
    first_email = f"auth_refresh_first_{_id()[:8]}@test.com"
    second_email = f"auth_refresh_second_{_id()[:8]}@test.com"
    await _seed_user(db_session, first_email, "pass")
    second_user = await _seed_user(db_session, second_email, "pass")
    await db_session.commit()

    async with _auth_client(db_session) as ac:
        login_response = await ac.post(
            "/api/v1/auth/token",
            json={"email": first_email, "password": "pass"},
        )
        assert login_response.status_code == 200, login_response.text
        refresh = login_response.json()["refresh_token"]
        claims = decode_refresh_token_claims(refresh)
        family = await db_session.scalar(
            select(RefreshTokenFamily).where(RefreshTokenFamily.family_id == claims.family_id)
        )
        assert family is not None
        family.user_id = second_user.id
        await db_session.commit()

        with pytest.raises(HTTPException) as exc_info:
            await refresh_endpoint(RefreshRequest(refresh_token=refresh), db_session)

    app.dependency_overrides.clear()
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_logout_ignores_refresh_token_with_tampered_server_binding(
    db_session: AsyncSession,
) -> None:
    """Logout remains non-enumerating without revoking a mismatched token family."""
    await app.state.rate_limiter.reset()
    email = f"auth_logout_binding_{_id()[:8]}@test.com"
    await _seed_user(db_session, email, "pass")
    await db_session.commit()

    async with _auth_client(db_session) as ac:
        login_response = await ac.post(
            "/api/v1/auth/token",
            json={"email": email, "password": "pass"},
        )
        assert login_response.status_code == 200, login_response.text
        refresh = login_response.json()["refresh_token"]
        claims = decode_refresh_token_claims(refresh)
        stored = await db_session.get(RefreshToken, claims.token_id)
        assert stored is not None
        stored.token_hash = "not-the-presented-token"
        await db_session.commit()

        logout_result = await logout_endpoint(
            RefreshRequest(refresh_token=refresh),
            db_session,
        )

    app.dependency_overrides.clear()
    assert logout_result is None
    family = await db_session.scalar(
        select(RefreshTokenFamily).where(RefreshTokenFamily.family_id == claims.family_id)
    )
    assert family is not None
    assert family.revoked_at is None


@pytest.mark.asyncio
async def test_me_endpoint(client: AsyncClient) -> None:
    """GET /api/v1/auth/me returns the stub caller identity."""
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "test@sentineliq.test"
    assert "platform_admin" in body["roles"]


# ===========================================================================
# Permission enforcement on events endpoints
# ===========================================================================


@pytest.mark.asyncio
async def test_events_endpoint_requires_auth() -> None:
    """GET /api/v1/events without a token returns 401."""
    app.dependency_overrides = {}  # no auth override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/v1/events")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_events_endpoint_forbidden_for_insufficient_role(
    db_session: AsyncSession,
) -> None:
    """
    A user with only 'audit_reviewer' (events:read only) cannot POST events
    (requires events:ingest).
    """
    # Build a stub with audit_reviewer only
    stub_user = User(
        id=_id(),
        email="limited@test.com",
        full_name="Limited",
        hashed_password="x",
        is_active=True,
        is_verified=True,
    )
    limited_auth = AuthenticatedUser(user=stub_user, roles=["audit_reviewer"])

    app.dependency_overrides[get_current_user] = lambda: limited_auth
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/events",
            json={
                "event_type": "person_detected",
                "event_timestamp": "2026-11-03T22:30:00Z",
                "location_id": "LOADING_DOCK_3",
            },
        )
    app.dependency_overrides.clear()

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "FORBIDDEN"
