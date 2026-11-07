"""
Admin API tests — Gate 19.

Tests cover:
- GET  /api/v1/admin/users          — list users (pagination, empty state)
- POST /api/v1/admin/users          — create user (happy path, duplicate email, invalid role)
- GET  /api/v1/admin/users/{id}     — get user detail
- PATCH /api/v1/admin/users/{id}    — update user (deactivate, rename)
- POST /api/v1/admin/users/{id}/roles    — assign role (happy path, idempotent, invalid role)
- DELETE /api/v1/admin/users/{id}/roles/{role} — remove role
- GET  /api/v1/admin/roles          — list all roles with permissions
- Authorization: 403 for every endpoint when caller lacks admin:users
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.main import app
from app.models.audit import AuditEvent
from app.models.user import VALID_ROLES, Role, User, UserRole
from app.security.dependencies import AuthenticatedUser, get_current_user
from app.security.passwords import hash_password


def _id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Fixtures — admin client (platform_admin) and non-admin client (officer)
# ---------------------------------------------------------------------------


def _make_stub(roles: list[str]) -> AuthenticatedUser:
    user = User(
        id=_id(),
        email=f"stub_{_id()[:6]}@test.com",
        full_name="Stub",
        hashed_password="$2b$12$unused",
        is_active=True,
        is_verified=True,
    )
    return AuthenticatedUser(user=user, roles=roles)


@pytest_asyncio.fixture
async def admin_client(db_session: AsyncSession):
    """AsyncClient authenticated as platform_admin."""
    stub = _make_stub(["platform_admin"])

    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: stub
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def officer_client(db_session: AsyncSession):
    """AsyncClient authenticated as officer — no admin:users permission."""
    stub = _make_stub(["officer"])

    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: stub
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_role(session: AsyncSession, name: str) -> Role:
    """Ensure a named Role row exists (reuse if present)."""
    from sqlalchemy import select

    result = await session.execute(select(Role).where(Role.name == name))
    role = result.scalar_one_or_none()
    if role is None:
        role = Role(id=_id(), name=name, description=name)
        session.add(role)
        await session.flush()
    return role


async def _seed_user(
    session: AsyncSession,
    email: str,
    role_name: str = "officer",
) -> User:
    role = await _seed_role(session, role_name)
    user = User(
        id=_id(),
        email=email,
        full_name="Test Person",
        hashed_password=hash_password("password123"),
        is_active=True,
        is_verified=False,
    )
    session.add(user)
    await session.flush()
    session.add(UserRole(id=_id(), user_id=user.id, role_id=role.id))
    await session.commit()
    return user


# ===========================================================================
# Authorization — every endpoint returns 403 for non-admin roles
# ===========================================================================


@pytest.mark.asyncio
async def test_list_users_requires_admin(officer_client: AsyncClient) -> None:
    resp = await officer_client.get("/api/v1/admin/users")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_user_requires_admin(officer_client: AsyncClient) -> None:
    resp = await officer_client.post(
        "/api/v1/admin/users",
        json={"email": "x@test.com", "full_name": "X", "password": "password123"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_get_user_requires_admin(officer_client: AsyncClient) -> None:
    resp = await officer_client.get(f"/api/v1/admin/users/{_id()}")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_update_user_requires_admin(officer_client: AsyncClient) -> None:
    resp = await officer_client.patch(
        f"/api/v1/admin/users/{_id()}",
        json={"is_active": False},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_assign_role_requires_admin(officer_client: AsyncClient) -> None:
    resp = await officer_client.post(
        f"/api/v1/admin/users/{_id()}/roles",
        json={"role": "officer"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_remove_role_requires_admin(officer_client: AsyncClient) -> None:
    resp = await officer_client.delete(f"/api/v1/admin/users/{_id()}/roles/officer")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_roles_requires_admin(officer_client: AsyncClient) -> None:
    resp = await officer_client.get("/api/v1/admin/roles")
    assert resp.status_code == 403


# ===========================================================================
# GET /api/v1/admin/users
# ===========================================================================


@pytest.mark.asyncio
async def test_list_users_returns_paginated_response(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    email = f"list_{_id()[:8]}@test.com"
    await _seed_user(db_session, email)

    resp = await admin_client.get("/api/v1/admin/users?page=1&page_size=50")
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert "total" in body
    assert "page" in body
    assert "page_size" in body
    assert "pages" in body
    assert body["page"] == 1
    emails = [u["email"] for u in body["items"]]
    assert email in emails


@pytest.mark.asyncio
async def test_list_users_includes_roles(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    email = f"roles_{_id()[:8]}@test.com"
    await _seed_user(db_session, email, role_name="supervisor")

    resp = await admin_client.get("/api/v1/admin/users")
    assert resp.status_code == 200
    user_item = next((u for u in resp.json()["items"] if u["email"] == email), None)
    assert user_item is not None
    assert "supervisor" in user_item["roles"]


# ===========================================================================
# POST /api/v1/admin/users
# ===========================================================================


@pytest.mark.asyncio
async def test_create_user_happy_path(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    await _seed_role(db_session, "officer")
    email = f"new_{_id()[:8]}@test.com"

    resp = await admin_client.post(
        "/api/v1/admin/users",
        json={
            "email": email,
            "full_name": "New Officer",
            "password": "password123",
            "roles": ["officer"],
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == email
    assert body["full_name"] == "New Officer"
    assert body["is_active"] is True
    role_names = [r["role"] for r in body["roles"]]
    assert "officer" in role_names

    created = await db_session.scalar(select(User).where(User.email == email))
    assert created is not None
    user_role = await db_session.scalar(select(UserRole).where(UserRole.user_id == created.id))
    assert user_role is not None
    assert user_role.granted_by is not None

    audit = await db_session.scalar(
        select(AuditEvent)
        .where(AuditEvent.action == "admin_user_created")
        .where(AuditEvent.actor.like("stub_%@test.com"))
        .order_by(AuditEvent.occurred_at.desc())
    )
    assert audit is not None
    assert audit.actor_role == "platform_admin"
    assert created.id in (audit.details_json or "")


@pytest.mark.asyncio
async def test_create_user_duplicate_email_returns_409(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    email = f"dup_{_id()[:8]}@test.com"
    await _seed_user(db_session, email)

    resp = await admin_client.post(
        "/api/v1/admin/users",
        json={"email": email, "full_name": "Dup", "password": "password123"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "EMAIL_TAKEN"


@pytest.mark.asyncio
async def test_create_user_invalid_role_returns_422(
    admin_client: AsyncClient,
) -> None:
    resp = await admin_client.post(
        "/api/v1/admin/users",
        json={
            "email": f"inv_{_id()[:8]}@test.com",
            "full_name": "Invalid",
            "password": "password123",
            "roles": ["nonexistent_role"],
        },
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "INVALID_ROLE"


@pytest.mark.asyncio
async def test_create_user_no_roles(
    admin_client: AsyncClient,
) -> None:
    resp = await admin_client.post(
        "/api/v1/admin/users",
        json={
            "email": f"noroles_{_id()[:8]}@test.com",
            "full_name": "No Roles",
            "password": "password123",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["roles"] == []


@pytest.mark.asyncio
async def test_admin_cannot_assign_service_role_through_human_user_api(
    admin_client: AsyncClient,
) -> None:
    resp = await admin_client.post(
        "/api/v1/admin/users",
        json={
            "email": f"service_{_id()[:8]}@test.com",
            "full_name": "Not a service provisioner",
            "password": "password123",
            "roles": ["agent_tool_reader"],
        },
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "SERVICE_ROLE_PROVISIONING_REQUIRED"


@pytest.mark.asyncio
async def test_user_create_rolls_back_when_audit_insert_fails(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    email = f"rollback_{_id()[:8]}@test.com"

    def reject_admin_audit(session, flush_context, instances) -> None:
        if any(
            isinstance(obj, AuditEvent) and obj.action == "admin_user_created"
            for obj in session.new
        ):
            raise RuntimeError("simulated audit persistence failure")

    event.listen(db_session.sync_session, "before_flush", reject_admin_audit)
    try:
        with pytest.raises(RuntimeError, match="audit persistence failure"):
            await admin_client.post(
                "/api/v1/admin/users",
                json={
                    "email": email,
                    "full_name": "Must Roll Back",
                    "password": "password123",
                },
            )
    finally:
        event.remove(db_session.sync_session, "before_flush", reject_admin_audit)

    assert await db_session.scalar(select(User).where(User.email == email)) is None


# ===========================================================================
# GET /api/v1/admin/users/{user_id}
# ===========================================================================


@pytest.mark.asyncio
async def test_get_user_returns_detail(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    email = f"detail_{_id()[:8]}@test.com"
    user = await _seed_user(db_session, email)

    resp = await admin_client.get(f"/api/v1/admin/users/{user.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == user.id
    assert body["email"] == email
    assert "roles" in body
    assert "created_at" in body


@pytest.mark.asyncio
async def test_get_user_not_found_returns_404(
    admin_client: AsyncClient,
) -> None:
    resp = await admin_client.get(f"/api/v1/admin/users/{_id()}")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "USER_NOT_FOUND"


# ===========================================================================
# PATCH /api/v1/admin/users/{user_id}
# ===========================================================================


@pytest.mark.asyncio
async def test_deactivate_user(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    email = f"deact_{_id()[:8]}@test.com"
    user = await _seed_user(db_session, email)

    resp = await admin_client.patch(
        f"/api/v1/admin/users/{user.id}",
        json={"is_active": False},
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False
    audit = await db_session.scalar(
        select(AuditEvent)
        .where(AuditEvent.action == "admin_user_deactivated")
        .where(AuditEvent.details_json.contains(user.id))
    )
    assert audit is not None


@pytest.mark.asyncio
async def test_rename_user(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    email = f"rename_{_id()[:8]}@test.com"
    user = await _seed_user(db_session, email)

    resp = await admin_client.patch(
        f"/api/v1/admin/users/{user.id}",
        json={"full_name": "Updated Name"},
    )
    assert resp.status_code == 200
    assert resp.json()["full_name"] == "Updated Name"
    audit = await db_session.scalar(
        select(AuditEvent)
        .where(AuditEvent.action == "admin_user_updated")
        .where(AuditEvent.details_json.contains(user.id))
    )
    assert audit is not None


@pytest.mark.asyncio
async def test_update_user_not_found(
    admin_client: AsyncClient,
) -> None:
    resp = await admin_client.patch(
        f"/api/v1/admin/users/{_id()}",
        json={"is_active": False},
    )
    assert resp.status_code == 404


# ===========================================================================
# POST /api/v1/admin/users/{user_id}/roles
# ===========================================================================


@pytest.mark.asyncio
async def test_assign_role_happy_path(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    await _seed_role(db_session, "supervisor")
    email = f"assign_{_id()[:8]}@test.com"
    user = await _seed_user(db_session, email, role_name="officer")

    resp = await admin_client.post(
        f"/api/v1/admin/users/{user.id}/roles",
        json={"role": "supervisor"},
    )
    assert resp.status_code == 200
    role_names = [r["role"] for r in resp.json()["roles"]]
    assert "supervisor" in role_names
    supervisor = await db_session.scalar(select(Role).where(Role.name == "supervisor"))
    assert supervisor is not None
    assignment = await db_session.scalar(
        select(UserRole).where(
            UserRole.user_id == user.id,
            UserRole.role_id == supervisor.id,
        )
    )
    assert assignment is not None
    assert assignment.granted_by is not None
    audit = await db_session.scalar(
        select(AuditEvent)
        .where(AuditEvent.action == "admin_role_granted")
        .where(AuditEvent.details_json.contains(user.id))
    )
    assert audit is not None


@pytest.mark.asyncio
async def test_assign_role_idempotent(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Assigning an already-held role is a no-op, not an error."""
    await _seed_role(db_session, "officer")
    email = f"idem_{_id()[:8]}@test.com"
    user = await _seed_user(db_session, email, role_name="officer")

    resp1 = await admin_client.post(
        f"/api/v1/admin/users/{user.id}/roles", json={"role": "officer"}
    )
    resp2 = await admin_client.post(
        f"/api/v1/admin/users/{user.id}/roles", json={"role": "officer"}
    )
    assert resp1.status_code == 200
    assert resp2.status_code == 200


@pytest.mark.asyncio
async def test_assign_invalid_role_returns_422(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    email = f"invassign_{_id()[:8]}@test.com"
    user = await _seed_user(db_session, email)

    resp = await admin_client.post(
        f"/api/v1/admin/users/{user.id}/roles",
        json={"role": "not_a_real_role"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_assign_role_user_not_found(
    admin_client: AsyncClient,
) -> None:
    resp = await admin_client.post(
        f"/api/v1/admin/users/{_id()}/roles",
        json={"role": "officer"},
    )
    assert resp.status_code == 404


# ===========================================================================
# DELETE /api/v1/admin/users/{user_id}/roles/{role}
# ===========================================================================


@pytest.mark.asyncio
async def test_remove_role_happy_path(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    await _seed_role(db_session, "officer")
    email = f"rmrole_{_id()[:8]}@test.com"
    user = await _seed_user(db_session, email, role_name="officer")

    resp = await admin_client.delete(f"/api/v1/admin/users/{user.id}/roles/officer")
    assert resp.status_code == 200
    role_names = [r["role"] for r in resp.json()["roles"]]
    assert "officer" not in role_names
    audit = await db_session.scalar(
        select(AuditEvent)
        .where(AuditEvent.action == "admin_role_removed")
        .where(AuditEvent.details_json.contains(user.id))
    )
    assert audit is not None


@pytest.mark.asyncio
async def test_remove_nonexistent_role_is_noop(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Removing a role the user doesn't hold is a no-op, not an error."""
    email = f"noop_{_id()[:8]}@test.com"
    user = await _seed_user(db_session, email, role_name="officer")

    # 'supervisor' is in VALID_ROLES but not assigned to this user
    await _seed_role(db_session, "supervisor")
    resp = await admin_client.delete(f"/api/v1/admin/users/{user.id}/roles/supervisor")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_remove_role_unknown_role_returns_404(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    email = f"unkrole_{_id()[:8]}@test.com"
    user = await _seed_user(db_session, email)
    resp = await admin_client.delete(f"/api/v1/admin/users/{user.id}/roles/completely_unknown")
    assert resp.status_code == 404


# ===========================================================================
# GET /api/v1/admin/roles
# ===========================================================================


@pytest.mark.asyncio
async def test_list_roles_returns_all_roles(
    admin_client: AsyncClient,
) -> None:
    resp = await admin_client.get("/api/v1/admin/roles")
    assert resp.status_code == 200
    body = resp.json()
    assert "roles" in body
    returned_names = {r["name"] for r in body["roles"]}
    for role in VALID_ROLES:
        assert role in returned_names, f"Role '{role}' missing from /admin/roles"


@pytest.mark.asyncio
async def test_list_roles_includes_permissions(
    admin_client: AsyncClient,
) -> None:
    resp = await admin_client.get("/api/v1/admin/roles")
    assert resp.status_code == 200
    roles_map = {r["name"]: r for r in resp.json()["roles"]}

    # platform_admin must have admin:users
    assert "admin:users" in roles_map["platform_admin"]["permissions"]
    # officer must NOT have admin:users
    assert "admin:users" not in roles_map["officer"]["permissions"]
    # Every role entry has a description
    for role in roles_map.values():
        assert role["description"]
        assert isinstance(role["permissions"], list)
