"""
Operator Decision API — Gate 10.

Routes:
    POST  /api/v1/events/{id}/decision    Record an operator decision
    GET   /api/v1/events/{id}/decision    Retrieve latest decision
    GET   /api/v1/events/{id}/decisions   Retrieve all decisions (history)

Design notes:
- Only events in 'awaiting_review' or 'escalated' may be decided.
  Any other status returns HTTP 409.
- Each POST creates an OperatorDecision row AND an immutable AuditEvent row.
- Decision type drives the state machine transition (DECISION_STATUS_MAP).
- The actor is derived from the authenticated JWT — operators cannot
  impersonate other users (ADR-006, human authority non-bypassable).
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.event import SecurityEvent
from app.schemas.decision import (
    VALID_DECISIONS,
    DecisionListResponse,
    DecisionRequest,
    DecisionResponse,
)
from app.schemas.events import ErrorDetail
from app.security.dependencies import AuthenticatedUser, require_permission
from app.security.rbac import has_permission
from app.services.decision_service import DecisionService
from app.services.event_lifecycle import InvalidTransitionError

logger = structlog.get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# POST /api/v1/events/{event_id}/decision — record a decision
# ---------------------------------------------------------------------------


@router.post(
    "/{event_id}/decision",
    response_model=DecisionResponse,
    status_code=201,
    summary="Record an operator decision on a security event",
    responses={
        201: {"description": "Decision recorded — event status advanced"},
        400: {"description": "Invalid decision type"},
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
        404: {"description": "Event not found"},
        409: {"description": "Event not in a decidable status or invalid transition"},
        422: {"description": "Validation error"},
    },
)
async def record_decision(
    event_id: str,
    body: DecisionRequest,
    session: AsyncSession = Depends(get_db),
    actor: AuthenticatedUser = Depends(require_permission("events:decide")),
) -> DecisionResponse:
    """
    Record an operator decision on a security event.

    The event must be in ``awaiting_review`` or ``escalated`` status.
    The decision type determines the resulting event status:

    | Decision | Resulting status |
    |----------|-----------------|
    | accept | closed |
    | reject | dismissed |
    | dismiss | dismissed |
    | escalate | escalated |
    | override | closed |
    | request_context | context_incomplete |

    A ``human_decision`` audit trail entry is created on every call.
    """
    # Validate decision type before hitting the DB
    if body.decision not in VALID_DECISIONS:
        raise HTTPException(
            status_code=400,
            detail=ErrorDetail(
                code="INVALID_DECISION",
                message=f"Unknown decision type '{body.decision}'. "
                f"Valid: {sorted(VALID_DECISIONS)}",
            ).model_dump(),
        )

    required_permissions: set[str] = set()
    if body.decision == "escalate":
        required_permissions.add("events:escalate")
    if body.decision == "override" or body.is_override:
        required_permissions.add("events:override")
    missing_permissions = sorted(
        permission
        for permission in required_permissions
        if not has_permission(actor.roles, permission)
    )
    if missing_permissions:
        raise HTTPException(
            status_code=403,
            detail=ErrorDetail(
                code="FORBIDDEN",
                message=f"Missing required permission(s): {', '.join(missing_permissions)}.",
            ).model_dump(),
        )

    try:
        service = DecisionService(session)
        result = await service.record(
            event_id,
            body.decision,
            rationale=body.rationale,
            recommendation_id=body.recommendation_id,
            is_override=body.is_override,
            actor=actor,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail=ErrorDetail(code="FORBIDDEN", message=str(exc)).model_dump(),
        ) from exc
    except ValueError as exc:
        msg = str(exc)
        status_code = 404 if "not found" in msg.lower() else 409
        raise HTTPException(
            status_code=status_code,
            detail=ErrorDetail(
                code="DECISION_ERROR",
                message=msg,
            ).model_dump(),
        ) from exc
    except InvalidTransitionError as exc:
        raise HTTPException(
            status_code=409,
            detail=ErrorDetail(
                code="INVALID_TRANSITION",
                message=str(exc),
            ).model_dump(),
        ) from exc

    return result


# ---------------------------------------------------------------------------
# GET /api/v1/events/{event_id}/decision — latest decision
# ---------------------------------------------------------------------------


@router.get(
    "/{event_id}/decision",
    response_model=DecisionResponse,
    summary="Retrieve the latest operator decision for an event",
    dependencies=[Depends(require_permission("events:read"))],
    responses={
        200: {"description": "Decision found"},
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
        404: {"description": "Event or decision not found"},
    },
)
async def get_latest_decision(
    event_id: str,
    session: AsyncSession = Depends(get_db),
) -> DecisionResponse:
    """
    Retrieve the most recent operator decision for a security event.

    Returns 404 if the event does not exist or no decision has been recorded.
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

    service = DecisionService(session)
    row = await service.get_latest(event_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorDetail(
                code="DECISION_NOT_FOUND",
                message=f"No decision has been recorded for event '{event_id}'.",
            ).model_dump(),
        )

    return DecisionResponse(
        decision_id=row.id,
        event_id=event_id,
        decision=row.decision,
        rationale=row.rationale,
        recommendation_id=row.recommendation_id,
        is_override=row.is_override,
        decided_by=row.decided_by,
        decided_by_role=row.decided_by_role,
        prior_status=row.prior_status,
        risk_at_decision=row.risk_at_decision,
        confidence_at_decision=row.confidence_at_decision,
        decided_at=row.decided_at,
        event_status=event.status,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/events/{event_id}/decisions — full decision history
# ---------------------------------------------------------------------------


@router.get(
    "/{event_id}/decisions",
    response_model=DecisionListResponse,
    summary="Retrieve all operator decisions for an event (history)",
    dependencies=[Depends(require_permission("events:read"))],
    responses={
        200: {"description": "Decision history"},
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
        404: {"description": "Event not found"},
    },
)
async def get_decision_history(
    event_id: str,
    session: AsyncSession = Depends(get_db),
) -> DecisionListResponse:
    """
    Return all operator decisions recorded for a security event, newest first.

    Returns an empty list (not 404) if the event exists but has no decisions.
    Returns 404 only if the event itself does not exist.
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

    service = DecisionService(session)
    rows = await service.get_all(event_id)

    items = [
        DecisionResponse(
            decision_id=row.id,
            event_id=event_id,
            decision=row.decision,
            rationale=row.rationale,
            recommendation_id=row.recommendation_id,
            is_override=row.is_override,
            decided_by=row.decided_by,
            decided_by_role=row.decided_by_role,
            prior_status=row.prior_status,
            risk_at_decision=row.risk_at_decision,
            confidence_at_decision=row.confidence_at_decision,
            decided_at=row.decided_at,
            event_status=event.status,
        )
        for row in rows
    ]

    return DecisionListResponse(
        event_id=event_id,
        items=items,
        total=len(items),
    )
