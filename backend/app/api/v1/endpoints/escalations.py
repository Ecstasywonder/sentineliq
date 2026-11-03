"""
Escalation API — Gate 11.

Routes:
    POST   /api/v1/events/{id}/escalation     Create escalation record
    GET    /api/v1/events/{id}/escalation     Retrieve latest escalation
    PATCH  /api/v1/events/{id}/escalation     Update escalation status

Design notes:
- Escalations are created automatically by the decision service when the
  operator records an 'escalate' decision, but can also be created
  explicitly via this endpoint for events already in 'escalated' status.
- The PATCH endpoint drives the escalation lifecycle:
    pending_acknowledgement → acknowledged → resolved | cancelled
- resolved transitions the event → closed
- cancelled transitions the event → awaiting_review (back to operator queue)
- Every state change writes an immutable AuditEvent row.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.event import SecurityEvent
from app.schemas.escalation import (
    VALID_DESTINATIONS,
    VALID_ESCALATION_STATUSES,
    VALID_PRIORITIES,
    EscalationCreateRequest,
    EscalationResponse,
    EscalationUpdateRequest,
)
from app.schemas.events import ErrorDetail
from app.security.dependencies import AuthenticatedUser, require_permission
from app.services.escalation_service import (
    EscalationService,
    InvalidEscalationTransitionError,
)

logger = structlog.get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# POST /api/v1/events/{event_id}/escalation — create
# ---------------------------------------------------------------------------


@router.post(
    "/{event_id}/escalation",
    response_model=EscalationResponse,
    status_code=201,
    summary="Create an escalation record for a security event",
    responses={
        201: {"description": "Escalation created"},
        400: {"description": "Invalid destination or priority"},
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
        404: {"description": "Event not found"},
        409: {"description": "Event not in escalated status"},
        422: {"description": "Validation error"},
    },
)
async def create_escalation(
    event_id: str,
    body: EscalationCreateRequest,
    session: AsyncSession = Depends(get_db),
    actor: AuthenticatedUser = Depends(require_permission("events:decide")),
) -> EscalationResponse:
    """
    Create an escalation record for a security event.

    The event must already be in ``escalated`` status — i.e. an operator
    must have previously recorded an ``escalate`` decision.

    Returns 409 if the event is not in ``escalated`` status.
    """
    if body.destination not in VALID_DESTINATIONS:
        raise HTTPException(
            status_code=400,
            detail=ErrorDetail(
                code="INVALID_DESTINATION",
                message=f"Unknown destination '{body.destination}'. "
                f"Valid: {sorted(VALID_DESTINATIONS)}",
            ).model_dump(),
        )
    if body.priority not in VALID_PRIORITIES:
        raise HTTPException(
            status_code=400,
            detail=ErrorDetail(
                code="INVALID_PRIORITY",
                message=f"Unknown priority '{body.priority}'. "
                f"Valid: {sorted(VALID_PRIORITIES)}",
            ).model_dump(),
        )

    try:
        service = EscalationService(session)
        result = await service.create(
            event_id,
            destination=body.destination,
            priority=body.priority,
            note=body.note,
            actor=actor,
        )
    except ValueError as exc:
        msg = str(exc)
        status_code = 404 if "not found" in msg.lower() else 409
        raise HTTPException(
            status_code=status_code,
            detail=ErrorDetail(
                code="ESCALATION_ERROR",
                message=msg,
            ).model_dump(),
        ) from exc

    return result


# ---------------------------------------------------------------------------
# GET /api/v1/events/{event_id}/escalation — retrieve latest
# ---------------------------------------------------------------------------


@router.get(
    "/{event_id}/escalation",
    response_model=EscalationResponse,
    summary="Retrieve the latest escalation for a security event",
    dependencies=[Depends(require_permission("events:read"))],
    responses={
        200: {"description": "Escalation found"},
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
        404: {"description": "Event or escalation not found"},
    },
)
async def get_escalation(
    event_id: str,
    session: AsyncSession = Depends(get_db),
) -> EscalationResponse:
    """
    Retrieve the most recent escalation record for a security event.

    Returns 404 if the event does not exist or has never been escalated.
    """
    event: SecurityEvent | None = await session.get(SecurityEvent, event_id)
    if event is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorDetail(
                code="EVENT_NOT_FOUND",
                message=f"Event '{event_id}' not found.",
            ).model_dump(),
        )

    service = EscalationService(session)
    row = await service.get_latest(event_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorDetail(
                code="ESCALATION_NOT_FOUND",
                message=f"No escalation found for event '{event_id}'.",
            ).model_dump(),
        )

    return EscalationService._to_response(row, event)


# ---------------------------------------------------------------------------
# PATCH /api/v1/events/{event_id}/escalation — update status
# ---------------------------------------------------------------------------


@router.patch(
    "/{event_id}/escalation",
    response_model=EscalationResponse,
    summary="Update escalation status (acknowledge / resolve / cancel)",
    responses={
        200: {"description": "Escalation updated"},
        400: {"description": "Invalid status"},
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
        404: {"description": "Event or escalation not found"},
        409: {"description": "Invalid escalation status transition"},
        422: {"description": "Validation error"},
    },
)
async def update_escalation(
    event_id: str,
    body: EscalationUpdateRequest,
    session: AsyncSession = Depends(get_db),
    actor: AuthenticatedUser = Depends(require_permission("events:decide")),
) -> EscalationResponse:
    """
    Advance an escalation to a new status.

    Valid transitions:
    - ``pending_acknowledgement`` → ``acknowledged`` | ``cancelled``
    - ``acknowledged`` → ``resolved`` | ``cancelled``

    ``resolved`` transitions the event to ``closed``.
    ``cancelled`` returns the event to ``awaiting_review``.
    """
    if body.status not in VALID_ESCALATION_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=ErrorDetail(
                code="INVALID_ESCALATION_STATUS",
                message=f"Unknown status '{body.status}'. "
                f"Valid: {sorted(VALID_ESCALATION_STATUSES)}",
            ).model_dump(),
        )

    # Verify event exists first
    event: SecurityEvent | None = await session.get(SecurityEvent, event_id)
    if event is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorDetail(
                code="EVENT_NOT_FOUND",
                message=f"Event '{event_id}' not found.",
            ).model_dump(),
        )

    try:
        service = EscalationService(session)
        result = await service.update_status(
            event_id,
            new_status=body.status,
            note=body.note,
            actor=actor,
        )
    except InvalidEscalationTransitionError as exc:
        raise HTTPException(
            status_code=409,
            detail=ErrorDetail(
                code="INVALID_ESCALATION_TRANSITION",
                message=str(exc),
            ).model_dump(),
        ) from exc
    except ValueError as exc:
        msg = str(exc)
        status_code = 404 if "not found" in msg.lower() else 409
        raise HTTPException(
            status_code=status_code,
            detail=ErrorDetail(
                code="ESCALATION_ERROR",
                message=msg,
            ).model_dump(),
        ) from exc

    return result
