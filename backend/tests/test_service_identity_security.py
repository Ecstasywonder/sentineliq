"""Gate 22 service-token least-privilege and purpose-isolation tests."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_db
from app.main import app
from app.models.user import Role, User, UserRole
from app.security.passwords import hash_password
from app.security.rbac import permissions_for_roles
from app.security.tokens import (
    SERVICE_TOKEN_AUDIENCE,
    TokenError,
    create_service_access_token,
    decode_access_token,
)


def _id() -> str:
    return str(uuid.uuid4())


async def _service_identity(
    session: AsyncSession,
    *,
    purpose: str,
    role_names: list[str],
) -> User:
    user = User(
        id=_id(),
        email=f"{purpose}-{_id()[:8]}@service.test.com",
        full_name=f"Service {purpose}",
        hashed_password=hash_password("unknown-service-password"),
        is_active=True,
        is_verified=True,
        service_purpose=purpose,
    )
    session.add(user)
    await session.flush()
    for role_name in role_names:
        role = await session.scalar(select(Role).where(Role.name == role_name))
        if role is None:
            role = Role(id=_id(), name=role_name, description=role_name)
            session.add(role)
            await session.flush()
        session.add(UserRole(user_id=user.id, role_id=role.id))
    await session.flush()
    return user


async def _raw_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_db
    await app.state.rate_limiter.reset()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        await app.state.rate_limiter.reset()
        if previous is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous


def test_service_token_has_explicit_audience_and_purpose() -> None:
    token = create_service_access_token("svc-1", ["agent_tool_reader"], "orchestrate_tools")
    payload = decode_access_token(token)
    assert payload["aud"] == SERVICE_TOKEN_AUDIENCE
    assert payload["purpose"] == "orchestrate_tools"


def test_service_roles_have_exact_least_privilege_permissions() -> None:
    assert permissions_for_roles(["agent_tool_reader"]) == frozenset({"tools:read"})
    assert permissions_for_roles(["event_ingestor"]) == frozenset({"events:ingest"})


def test_service_token_rejects_wrong_audience() -> None:
    settings = get_settings()
    token = jwt.encode(
        {
            "sub": "svc-1",
            "roles": ["agent_tool_reader"],
            "type": "access",
            "aud": "some-other-service",
            "purpose": "orchestrate_tools",
        },
        settings.secret_key,
        algorithm=settings.algorithm,
    )
    with pytest.raises(TokenError, match="audience or purpose"):
        decode_access_token(token)


@pytest.mark.asyncio
async def test_orchestrate_token_is_bounded_even_after_admin_role_misassignment(
    db_session: AsyncSession,
) -> None:
    user = await _service_identity(
        db_session,
        purpose="orchestrate_tools",
        role_names=["agent_tool_reader", "platform_admin"],
    )
    token = create_service_access_token(user.id, ["agent_tool_reader"], "orchestrate_tools")
    headers = {"Authorization": f"Bearer {token}"}

    async for client in _raw_client(db_session):
        tool_response = await client.get("/api/v1/tools/integration-health", headers=headers)
        admin_response = await client.get("/api/v1/admin/users", headers=headers)
        human_response = await client.get("/api/v1/auth/me", headers=headers)

    assert tool_response.status_code == 200
    assert admin_response.status_code == 403
    assert admin_response.json()["detail"]["code"] == "SERVICE_PURPOSE_FORBIDDEN"
    assert human_response.status_code == 403
    assert human_response.json()["detail"]["code"] == "HUMAN_TOKEN_REQUIRED"


@pytest.mark.asyncio
async def test_signed_role_claims_cannot_expand_service_authority(
    db_session: AsyncSession,
) -> None:
    user = await _service_identity(
        db_session,
        purpose="orchestrate_tools",
        role_names=["agent_tool_reader"],
    )
    token = create_service_access_token(
        user.id,
        ["agent_tool_reader", "platform_admin"],
        "orchestrate_tools",
    )

    async for client in _raw_client(db_session):
        response = await client.get(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "SERVICE_PURPOSE_FORBIDDEN"


@pytest.mark.asyncio
async def test_event_ingestor_token_cannot_read_or_decide_events(
    db_session: AsyncSession,
) -> None:
    user = await _service_identity(
        db_session,
        purpose="event_ingestion",
        role_names=["event_ingestor", "officer"],
    )
    token = create_service_access_token(user.id, ["event_ingestor"], "event_ingestion")
    headers = {"Authorization": f"Bearer {token}"}

    async for client in _raw_client(db_session):
        ingest_response = await client.post(
            "/api/v1/events",
            headers=headers,
            json={
                "event_type": "person_detected",
                "event_timestamp": "2026-11-07T10:00:00Z",
                "location_id": "LOADING_DOCK_3",
            },
        )
        read_response = await client.get("/api/v1/events", headers=headers)

    assert ingest_response.status_code == 201
    assert read_response.status_code == 403
    assert read_response.json()["detail"]["code"] == "SERVICE_PURPOSE_FORBIDDEN"


@pytest.mark.asyncio
async def test_service_identity_cannot_use_password_login(db_session: AsyncSession) -> None:
    user = await _service_identity(
        db_session,
        purpose="orchestrate_tools",
        role_names=["agent_tool_reader"],
    )
    user.hashed_password = hash_password("known-password")
    await db_session.flush()

    async for client in _raw_client(db_session):
        response = await client.post(
            "/api/v1/auth/token",
            json={"email": user.email, "password": "known-password"},
        )

    assert response.status_code == 403, response.text
    assert response.json()["detail"]["code"] == "SERVICE_ACCOUNT_LOGIN_DISABLED"
