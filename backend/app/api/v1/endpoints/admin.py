"""
Admin endpoints — Gate 19.

Routes (all require admin:users permission):
    GET    /api/v1/admin/users                  List users (paginated)
    POST   /api/v1/admin/users                  Create a new user
    GET    /api/v1/admin/users/{user_id}         Get user detail with roles
    PATCH  /api/v1/admin/users/{user_id}         Update full_name / is_active
    POST   /api/v1/admin/users/{user_id}/roles   Assign a role
    DELETE /api/v1/admin/users/{user_id}/roles/{role}  Remove a role

    GET    /api/v1/admin/roles                  List all roles with permissions
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.audit import AuditEvent
from app.models.user import HUMAN_ROLES, SERVICE_ROLES, VALID_ROLES, Role, User, UserRole
from app.schemas.admin import (
    RoleAssignRequest,
    RoleDescription,
    RolesResponse,
    UserCreateRequest,
    UserDetailResponse,
    UserListItem,
    UserListResponse,
    UserRoleSummary,
    UserUpdateRequest,
)
from app.security.dependencies import AuthenticatedUser, require_permission
from app.security.passwords import hash_password
from app.security.rbac import _ROLE_PERMISSIONS, has_permission

logger = structlog.get_logger(__name__)
router = APIRouter()

_ADMIN_DEP = Depends(require_permission("admin:users"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _load_user_or_404(session: AsyncSession, user_id: str) -> User:
    user: User | None = await session.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "USER_NOT_FOUND", "message": "User not found."},
        )
    return user


async def _roles_for_user(session: AsyncSession, user_id: str) -> list[UserRole]:
    result = await session.execute(select(UserRole).where(UserRole.user_id == user_id))
    return list(result.scalars().all())


async def _role_names_for_user(session: AsyncSession, user_id: str) -> list[str]:
    result = await session.execute(
        select(Role.name)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
    )
    return list(result.scalars().all())


def _format_ts(ts) -> str:  # type: ignore[type-arg]
    return ts.isoformat() if ts else ""


def _append_admin_audit(
    session: AsyncSession,
    *,
    action: str,
    actor: AuthenticatedUser,
    target: User,
    details: dict,
) -> None:
    """Stage an admin audit row in the caller's mutation transaction."""
    authorizing_role = next(
        (role for role in sorted(actor.roles) if has_permission([role], "admin:users")),
        None,
    )
    session.add(
        AuditEvent(
            action=action,
            actor=actor.email,
            actor_role=authorizing_role,
            occurred_at=datetime.now(UTC).isoformat(),
            details_json=json.dumps({"target_user_id": target.id, **details}, sort_keys=True),
        )
    )


async def _commit_admin_transaction(session: AsyncSession) -> None:
    """Commit mutation and audit atomically, returning the session to a usable state on failure."""
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise


async def _flush_admin_transaction(session: AsyncSession) -> None:
    """Flush safely when an identifier is needed before the audit row is staged."""
    try:
        await session.flush()
    except Exception:
        await session.rollback()
        raise


def _reject_service_role_assignment(role_names: list[str]) -> None:
    requested_service_roles = sorted(set(role_names).intersection(SERVICE_ROLES))
    if requested_service_roles:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "SERVICE_ROLE_PROVISIONING_REQUIRED",
                "message": "Service roles require the dedicated service-identity provisioner.",
            },
        )


# ---------------------------------------------------------------------------
# GET /api/v1/admin/users
# ---------------------------------------------------------------------------


@router.get(
    "/users",
    response_model=UserListResponse,
    dependencies=[_ADMIN_DEP],
    summary="List all users (paginated)",
)
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db),
) -> UserListResponse:
    offset = (page - 1) * page_size

    count_result = await session.execute(select(func.count()).select_from(User))
    total: int = count_result.scalar_one()

    users_result = await session.execute(
        select(User).order_by(User.created_at.asc()).offset(offset).limit(page_size)
    )
    users = list(users_result.scalars().all())

    items: list[UserListItem] = []
    for u in users:
        role_names = await _role_names_for_user(session, u.id)
        items.append(
            UserListItem(
                id=u.id,
                email=u.email,
                full_name=u.full_name,
                is_active=u.is_active,
                roles=role_names,
                created_at=_format_ts(u.created_at),
            )
        )

    return UserListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=max(1, math.ceil(total / page_size)),
    )


# ---------------------------------------------------------------------------
# POST /api/v1/admin/users
# ---------------------------------------------------------------------------


@router.post(
    "/users",
    response_model=UserDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new user",
)
async def create_user(
    body: UserCreateRequest,
    session: AsyncSession = Depends(get_db),
    actor: AuthenticatedUser = _ADMIN_DEP,
) -> UserDetailResponse:
    # Email uniqueness check
    existing = await session.execute(select(User).where(User.email == body.email.lower()))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "EMAIL_TAKEN", "message": "A user with this email already exists."},
        )

    # Validate requested roles
    _reject_service_role_assignment(body.roles)
    invalid_roles = [r for r in body.roles if r not in HUMAN_ROLES]
    if invalid_roles:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INVALID_ROLE",
                "message": f"Unknown role(s): {', '.join(invalid_roles)}. "
                f"Valid roles: {', '.join(HUMAN_ROLES)}",
            },
        )

    user = User(
        email=body.email.lower(),
        full_name=body.full_name,
        hashed_password=hash_password(body.password),
        is_active=True,
        is_verified=False,
    )
    session.add(user)
    await _flush_admin_transaction(session)  # get user.id

    assigned: list[UserRoleSummary] = []
    for role_name in body.roles:
        role_result = await session.execute(select(Role).where(Role.name == role_name))
        role = role_result.scalar_one_or_none()
        if role:
            session.add(UserRole(user_id=user.id, role_id=role.id, granted_by=actor.id))
            assigned.append(UserRoleSummary(role=role_name, granted_by=actor.id))
            _append_admin_audit(
                session,
                action="admin_role_granted",
                actor=actor,
                target=user,
                details={"role": role_name, "during_user_creation": True},
            )

    _append_admin_audit(
        session,
        action="admin_user_created",
        actor=actor,
        target=user,
        details={"roles": sorted(body.roles)},
    )
    await _commit_admin_transaction(session)
    logger.info("admin.user_created", user_id=user.id, email=user.email, roles=body.roles)

    return UserDetailResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        is_verified=user.is_verified,
        roles=assigned,
        created_at=_format_ts(user.created_at),
    )


# ---------------------------------------------------------------------------
# GET /api/v1/admin/users/{user_id}
# ---------------------------------------------------------------------------


@router.get(
    "/users/{user_id}",
    response_model=UserDetailResponse,
    dependencies=[_ADMIN_DEP],
    summary="Get user detail with roles",
)
async def get_user(
    user_id: str,
    session: AsyncSession = Depends(get_db),
) -> UserDetailResponse:
    user = await _load_user_or_404(session, user_id)
    user_roles = await _roles_for_user(session, user_id)

    role_summaries: list[UserRoleSummary] = []
    for ur in user_roles:
        role: Role | None = await session.get(Role, ur.role_id)
        if role:
            role_summaries.append(UserRoleSummary(role=role.name, granted_by=ur.granted_by))

    return UserDetailResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        is_verified=user.is_verified,
        roles=role_summaries,
        created_at=_format_ts(user.created_at),
    )


# ---------------------------------------------------------------------------
# PATCH /api/v1/admin/users/{user_id}
# ---------------------------------------------------------------------------


@router.patch(
    "/users/{user_id}",
    response_model=UserDetailResponse,
    summary="Update user full_name or is_active",
)
async def update_user(
    user_id: str,
    body: UserUpdateRequest,
    session: AsyncSession = Depends(get_db),
    actor: AuthenticatedUser = _ADMIN_DEP,
) -> UserDetailResponse:
    user = await _load_user_or_404(session, user_id)

    prior_full_name = user.full_name
    prior_is_active = user.is_active
    if body.full_name is not None:
        user.full_name = body.full_name
    if body.is_active is not None:
        user.is_active = body.is_active

    if user.full_name != prior_full_name:
        _append_admin_audit(
            session,
            action="admin_user_updated",
            actor=actor,
            target=user,
            details={"changes": {"full_name": {"from": prior_full_name, "to": user.full_name}}},
        )
    if user.is_active != prior_is_active:
        _append_admin_audit(
            session,
            action=(
                "admin_user_deactivated"
                if prior_is_active and not user.is_active
                else "admin_user_updated"
            ),
            actor=actor,
            target=user,
            details={"changes": {"is_active": {"from": prior_is_active, "to": user.is_active}}},
        )
    await _commit_admin_transaction(session)
    logger.info("admin.user_updated", user_id=user_id)

    user_roles = await _roles_for_user(session, user_id)
    role_summaries: list[UserRoleSummary] = []
    for ur in user_roles:
        role: Role | None = await session.get(Role, ur.role_id)
        if role:
            role_summaries.append(UserRoleSummary(role=role.name, granted_by=ur.granted_by))

    return UserDetailResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        is_verified=user.is_verified,
        roles=role_summaries,
        created_at=_format_ts(user.created_at),
    )


# ---------------------------------------------------------------------------
# POST /api/v1/admin/users/{user_id}/roles
# ---------------------------------------------------------------------------


@router.post(
    "/users/{user_id}/roles",
    response_model=UserDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Assign a role to a user",
)
async def assign_role(
    user_id: str,
    body: RoleAssignRequest,
    session: AsyncSession = Depends(get_db),
    actor: AuthenticatedUser = _ADMIN_DEP,
) -> UserDetailResponse:
    _reject_service_role_assignment([body.role])
    if body.role not in VALID_ROLES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INVALID_ROLE",
                "message": f"Unknown role '{body.role}'. Valid roles: {', '.join(VALID_ROLES)}",
            },
        )

    user = await _load_user_or_404(session, user_id)

    role_result = await session.execute(select(Role).where(Role.name == body.role))
    role = role_result.scalar_one_or_none()
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ROLE_NOT_FOUND", "message": f"Role '{body.role}' not in database."},
        )

    # Idempotent — skip if already assigned
    existing = await session.execute(
        select(UserRole).where(
            UserRole.user_id == user_id,
            UserRole.role_id == role.id,
        )
    )
    if existing.scalar_one_or_none() is None:
        session.add(UserRole(user_id=user_id, role_id=role.id, granted_by=actor.id))
        _append_admin_audit(
            session,
            action="admin_role_granted",
            actor=actor,
            target=user,
            details={"role": body.role},
        )
        await _commit_admin_transaction(session)
        logger.info("admin.role_assigned", user_id=user_id, role=body.role)

    user_roles = await _roles_for_user(session, user_id)
    role_summaries: list[UserRoleSummary] = []
    for ur in user_roles:
        r: Role | None = await session.get(Role, ur.role_id)
        if r:
            role_summaries.append(UserRoleSummary(role=r.name, granted_by=ur.granted_by))

    return UserDetailResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        is_verified=user.is_verified,
        roles=role_summaries,
        created_at=_format_ts(user.created_at),
    )


# ---------------------------------------------------------------------------
# DELETE /api/v1/admin/users/{user_id}/roles/{role}
# ---------------------------------------------------------------------------


@router.delete(
    "/users/{user_id}/roles/{role}",
    response_model=UserDetailResponse,
    summary="Remove a role from a user",
)
async def remove_role(
    user_id: str,
    role: str,
    session: AsyncSession = Depends(get_db),
    actor: AuthenticatedUser = _ADMIN_DEP,
) -> UserDetailResponse:
    _reject_service_role_assignment([role])
    user = await _load_user_or_404(session, user_id)

    role_result = await session.execute(select(Role).where(Role.name == role))
    role_obj = role_result.scalar_one_or_none()
    if role_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ROLE_NOT_FOUND", "message": f"Role '{role}' not found."},
        )

    ur_result = await session.execute(
        select(UserRole).where(
            UserRole.user_id == user_id,
            UserRole.role_id == role_obj.id,
        )
    )
    ur = ur_result.scalar_one_or_none()
    if ur is not None:
        await session.delete(ur)
        _append_admin_audit(
            session,
            action="admin_role_removed",
            actor=actor,
            target=user,
            details={"role": role},
        )
        await _commit_admin_transaction(session)
        logger.info("admin.role_removed", user_id=user_id, role=role)

    user_roles = await _roles_for_user(session, user_id)
    role_summaries: list[UserRoleSummary] = []
    for user_role in user_roles:
        r: Role | None = await session.get(Role, user_role.role_id)
        if r:
            role_summaries.append(UserRoleSummary(role=r.name, granted_by=user_role.granted_by))

    return UserDetailResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        is_verified=user.is_verified,
        roles=role_summaries,
        created_at=_format_ts(user.created_at),
    )


# ---------------------------------------------------------------------------
# GET /api/v1/admin/roles
# ---------------------------------------------------------------------------


@router.get(
    "/roles",
    response_model=RolesResponse,
    dependencies=[_ADMIN_DEP],
    summary="List all roles with their permission sets",
)
async def list_roles() -> RolesResponse:
    """Return all platform roles with their descriptions and permission sets.

    This is a static reference — it derives from the RBAC module, not the DB.
    """
    _role_descriptions = {
        "officer": "Security Monitoring Officer — reviews events, makes decisions, escalates",
        "supervisor": "Shift Supervisor — oversees officers, can override decisions, views audit trail",
        "response_team": "Response Team — views events and responds to incidents",
        "facility_manager": "Facility Manager — read-only access to events and audit trail",
        "security_admin": "Security Administrator — manages policies, risk configuration, and integrations",
        "audit_reviewer": "Compliance/Audit Reviewer — read-only access to decisions and audit trail",
        "platform_admin": "Platform Administrator — full access including user and role management",
        "agent_admin": "AI/Agent Administrator — manages agent configuration and model settings",
        "agent_tool_reader": "Machine identity — read-only access to Orchestrate context tools",
        "event_ingestor": "Machine identity — event ingestion only",
    }

    roles = [
        RoleDescription(
            name=role_name,
            description=_role_descriptions.get(role_name, role_name),
            permissions=sorted(_ROLE_PERMISSIONS.get(role_name, frozenset())),
        )
        for role_name in VALID_ROLES
    ]
    return RolesResponse(roles=roles)
