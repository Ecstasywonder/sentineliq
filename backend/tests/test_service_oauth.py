"""OAuth2 client-credentials contract for the Orchestrate tool identity."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints import auth as auth_endpoints
from app.config import Settings
from app.models.user import Role, User, UserRole
from app.security.tokens import decode_access_token

pytestmark = pytest.mark.asyncio

_CLIENT_ID = "sentineliq-orchestrate-tools"
_CLIENT_SECRET = "test-only-client-secret-at-least-32-chars"


def _oauth_settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        orchestrate_tools_client_id=_CLIENT_ID,
        orchestrate_tools_client_secret=SecretStr(_CLIENT_SECRET),
    )


async def _service_identity(
    session: AsyncSession,
    *,
    role_name: str = "agent_tool_reader",
    purpose: str | None = "orchestrate_tools",
    is_active: bool = True,
) -> User:
    role = Role(
        id=str(uuid.uuid4()),
        name=role_name,
        description="service oauth test role",
        is_active=True,
    )
    user = User(
        id=str(uuid.uuid4()),
        email=f"{uuid.uuid4()}@service.sentineliq.test",
        full_name="Service OAuth Test",
        hashed_password="unused-service-password-hash",
        is_active=is_active,
        is_verified=True,
        service_purpose=purpose,
    )
    session.add_all([role, user])
    await session.flush()
    session.add(
        UserRole(
            id=str(uuid.uuid4()),
            user_id=user.id,
            role_id=role.id,
            granted_by="test",
        )
    )
    await session.flush()
    return user


async def test_service_token_issues_short_lived_purpose_bound_token(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await _service_identity(db_session)
    settings = _oauth_settings()
    monkeypatch.setattr(auth_endpoints, "get_settings", lambda: settings)

    response = await client.post(
        "/api/v1/auth/service-token",
        data={"grant_type": "client_credentials", "scope": "tools:read"},
        auth=(_CLIENT_ID, _CLIENT_SECRET),
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"access_token", "token_type", "expires_in", "scope"}
    assert body["token_type"] == "Bearer"
    assert body["scope"] == "tools:read"
    assert body["expires_in"] == settings.access_token_expire_minutes * 60
    assert response.headers["cache-control"] == "no-store"
    claims = decode_access_token(body["access_token"])
    assert claims["sub"] == user.id
    assert claims["roles"] == ["agent_tool_reader"]
    assert claims["aud"] == "sentineliq-service"
    assert claims["purpose"] == "orchestrate_tools"


@pytest.mark.parametrize(
    ("client_id", "client_secret"),
    [
        ("wrong-client", _CLIENT_SECRET),
        (_CLIENT_ID, "wrong-secret"),
    ],
)
async def test_service_token_rejects_bad_client_without_echoing_credentials(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    client_id: str,
    client_secret: str,
) -> None:
    await _service_identity(db_session)
    monkeypatch.setattr(auth_endpoints, "get_settings", _oauth_settings)

    response = await client.post(
        "/api/v1/auth/service-token",
        data={"grant_type": "client_credentials"},
        auth=(client_id, client_secret),
    )

    assert response.status_code == 401
    assert response.json()["detail"]["error"] == "invalid_client"
    assert _CLIENT_SECRET not in response.text
    assert client_secret not in response.text


@pytest.mark.parametrize(
    ("form", "expected_error"),
    [
        ({"grant_type": "password"}, "unsupported_grant_type"),
        ({"grant_type": "client_credentials", "scope": "events:read"}, "invalid_scope"),
        (
            {"grant_type": "client_credentials", "scope": "tools:read events:read"},
            "invalid_scope",
        ),
    ],
)
async def test_service_token_rejects_grant_or_scope_expansion(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    form: dict[str, str],
    expected_error: str,
) -> None:
    await _service_identity(db_session)
    monkeypatch.setattr(auth_endpoints, "get_settings", _oauth_settings)

    response = await client.post(
        "/api/v1/auth/service-token",
        data=form,
        auth=(_CLIENT_ID, _CLIENT_SECRET),
    )

    assert response.status_code == 400
    assert response.json()["detail"]["error"] == expected_error


@pytest.mark.parametrize(
    ("role_name", "purpose", "is_active"),
    [
        ("platform_admin", "orchestrate_tools", True),
        ("agent_tool_reader", None, True),
        ("agent_tool_reader", "orchestrate_tools", False),
    ],
)
async def test_service_token_requires_exact_active_purpose_bound_identity(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    role_name: str,
    purpose: str | None,
    is_active: bool,
) -> None:
    await _service_identity(
        db_session,
        role_name=role_name,
        purpose=purpose,
        is_active=is_active,
    )
    monkeypatch.setattr(auth_endpoints, "get_settings", _oauth_settings)

    response = await client.post(
        "/api/v1/auth/service-token",
        data={"grant_type": "client_credentials"},
        auth=(_CLIENT_ID, _CLIENT_SECRET),
    )

    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "temporarily_unavailable"


async def test_service_token_fails_closed_when_client_config_is_absent(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(_env_file=None, app_env="test")
    monkeypatch.setattr(auth_endpoints, "get_settings", lambda: settings)

    response = await client.post(
        "/api/v1/auth/service-token",
        data={"grant_type": "client_credentials"},
        auth=(_CLIENT_ID, _CLIENT_SECRET),
    )

    assert response.status_code == 503
    assert _CLIENT_SECRET not in response.text
