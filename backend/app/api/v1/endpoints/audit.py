"""
Audit Trail API — Gate 12.

Routes:
    GET  /api/v1/events/{id}/audit    Full audit trail for a single event
    GET  /api/v1/audit                Global audit trail (paginated, filtered)

Design notes:
- Audit trail is INSERT-only — no write endpoints exist.
- details_json is deserialised to a dict before returning.
  Redacted rows return details=null (field is blanked in DB, not omitted).
- Global endpoint supports filtering by action, actor, and date range.
- Both endpoints require 'audit:read' permission (admin/supervisor roles).
"""

from __future__ import annotations

import json
import math

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.audit import AUDIT_ACTIONS, AuditEvent
from app.models.event import SecurityEvent
from app.schemas.audit import AuditEntryResponse, AuditListResponse
from app.schemas.events import ErrorDetail
from app.security.dependencies import require_permission

logger = structlog.get_logger(__name__)

router = APIRouter()


def _row_to_response(row: AuditEvent) -> AuditEntryResponse:
    """Convert an AuditEvent ORM row to the response schema."""
    details: dict | None = None
    if row.details_json and not row.redacted:
        try:
            details = json.loads(row.details_json)
        except (ValueError, TypeError):
            details = None
    return AuditEntryResponse(
        audit_id=row.id,
        event_id=row.event_id,
        action=row.action,
        actor=row.actor,
        actor_role=row.actor_role,
        occurred_at=row.occurred_at,
        details=details,
        redacted=row.redacted,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/events/{event_id}/audit — event-scoped audit trail
# ---------------------------------------------------------------------------


@router.get(
    "/events/{event_id}/audit",
    response_model=AuditListResponse,
    summary="Full audit trail for a single security event",
    dependencies=[Depends(require_permission("audit:read"))],
    responses={
        200: {"description": "Audit trail returned"},
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
        404: {"description": "Event not found"},
    },
)
async def get_event_audit(
    event_id: str,
    page: int = Query(default=1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(default=50, ge=1, le=200, description="Items per page"),
    session: AsyncSession = Depends(get_db),
) -> AuditListResponse:
    """
    Return the full immutable audit trail for a security event, newest first.

    Includes entries written by assessment, decisions, escalations, and any
    status changes.  Redacted entries are included but ``details`` is null.
    """
    # Verify event exists
    event: SecurityEvent | None = await session.get(SecurityEvent, event_id)
    if event is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorDetail(
                code="EVENT_NOT_FOUND",
                message=f"Event '{event_id}' not found.",
            ).model_dump(),
        )

    # Count
    count_stmt = (
        select(func.count())
        .select_from(AuditEvent)
        .where(AuditEvent.event_id == event_id)
    )
    total: int = (await session.execute(count_stmt)).scalar_one()

    # Fetch page
    stmt = (
        select(AuditEvent)
        .where(AuditEvent.event_id == event_id)
        .order_by(AuditEvent.occurred_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    pages = max(1, math.ceil(total / page_size))

    return AuditListResponse(
        items=[_row_to_response(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/audit — global audit trail
# ---------------------------------------------------------------------------


@router.get(
    "/audit",
    response_model=AuditListResponse,
    summary="Global audit trail with optional filtering",
    dependencies=[Depends(require_permission("audit:read"))],
    responses={
        200: {"description": "Audit trail returned"},
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
        422: {"description": "Invalid filter value"},
    },
)
async def get_global_audit(
    action: str | None = Query(
        default=None,
        description=f"Filter by action. Valid: {sorted(AUDIT_ACTIONS)}",
    ),
    actor: str | None = Query(
        default=None,
        description="Filter by actor email (exact match).",
    ),
    since: str | None = Query(
        default=None,
        description="Return entries at or after this ISO 8601 timestamp.",
    ),
    until: str | None = Query(
        default=None,
        description="Return entries at or before this ISO 8601 timestamp.",
    ),
    page: int = Query(default=1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(default=50, ge=1, le=200, description="Items per page"),
    session: AsyncSession = Depends(get_db),
) -> AuditListResponse:
    """
    Return the global audit trail across all events, newest first.

    Supports optional filtering by ``action``, ``actor`` email,
    and ``since`` / ``until`` ISO 8601 timestamps.
    """
    if action is not None and action not in AUDIT_ACTIONS:
        raise HTTPException(
            status_code=422,
            detail=ErrorDetail(
                code="INVALID_ACTION",
                message=f"Unknown action '{action}'. "
                f"Valid: {sorted(AUDIT_ACTIONS)}",
            ).model_dump(),
        )

    # Build base query
    base = select(AuditEvent)
    count_base = select(func.count()).select_from(AuditEvent)

    if action is not None:
        base = base.where(AuditEvent.action == action)
        count_base = count_base.where(AuditEvent.action == action)
    if actor is not None:
        base = base.where(AuditEvent.actor == actor)
        count_base = count_base.where(AuditEvent.actor == actor)
    if since is not None:
        base = base.where(AuditEvent.occurred_at >= since)
        count_base = count_base.where(AuditEvent.occurred_at >= since)
    if until is not None:
        base = base.where(AuditEvent.occurred_at <= until)
        count_base = count_base.where(AuditEvent.occurred_at <= until)

    total: int = (await session.execute(count_base)).scalar_one()

    stmt = (
        base
        .order_by(AuditEvent.occurred_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    pages = max(1, math.ceil(total / page_size))

    return AuditListResponse(
        items=[_row_to_response(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )
