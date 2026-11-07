"""
Feedback API — Gate 13.

Routes:
    POST  /api/v1/events/{id}/feedback    Submit feedback on an assessment
    GET   /api/v1/events/{id}/feedback    Retrieve all feedback for an event

Design notes:
- Feedback may be submitted at any time after an event exists (no status
  restriction — late retrospective feedback is valuable).
- Multiple feedback records per event are allowed (e.g. shift supervisor
  submits different feedback from initial operator).
- Each POST writes an immutable AuditEvent row (action='feedback_submitted').
- Outcome validation is enforced: only VALID_OUTCOMES are accepted.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.audit import AuditEvent
from app.models.event import SecurityEvent
from app.models.feedback import Feedback
from app.schemas.events import ErrorDetail
from app.schemas.feedback import (
    VALID_OUTCOMES,
    FeedbackListResponse,
    FeedbackRequest,
    FeedbackResponse,
)
from app.security.dependencies import AuthenticatedUser, require_permission

logger = structlog.get_logger(__name__)

router = APIRouter()


def _row_to_response(row: Feedback) -> FeedbackResponse:
    return FeedbackResponse(
        feedback_id=row.id,
        event_id=row.event_id,
        submitted_by=row.submitted_by,
        recommendation_useful=row.recommendation_useful,
        recommendation_accurate=row.recommendation_accurate,
        outcome=row.outcome,
        missing_context=row.missing_context,
        notes=row.notes,
        submitted_at=row.submitted_at,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/events/{event_id}/feedback — submit
# ---------------------------------------------------------------------------


@router.post(
    "/{event_id}/feedback",
    response_model=FeedbackResponse,
    status_code=201,
    summary="Submit feedback on a security event assessment",
    responses={
        201: {"description": "Feedback recorded"},
        400: {"description": "Invalid outcome value"},
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
        404: {"description": "Event not found"},
        422: {"description": "Validation error"},
    },
)
async def submit_feedback(
    event_id: str,
    body: FeedbackRequest,
    session: AsyncSession = Depends(get_db),
    actor: AuthenticatedUser = Depends(require_permission("events:read")),
) -> FeedbackResponse:
    """
    Submit operator or reviewer feedback on a security event's assessment.

    Feedback may be submitted at any lifecycle stage — including after the
    event is closed — to support retrospective quality review.

    Multiple feedback submissions per event are permitted.  Each submission
    creates an immutable ``feedback_submitted`` audit trail entry.
    """
    if body.outcome is not None and body.outcome not in VALID_OUTCOMES:
        raise HTTPException(
            status_code=400,
            detail=ErrorDetail(
                code="INVALID_OUTCOME",
                message=f"Unknown outcome '{body.outcome}'. Valid: {sorted(VALID_OUTCOMES)}",
            ).model_dump(),
        )

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

    submitted_at = datetime.now(UTC).isoformat()
    actor_role = actor.roles[0] if actor.roles else "unknown"

    # Persist Feedback row
    row = Feedback(
        id=str(uuid.uuid4()),
        event_id=event_id,
        submitted_by=actor.id,
        recommendation_useful=body.recommendation_useful,
        recommendation_accurate=body.recommendation_accurate,
        outcome=body.outcome,
        missing_context=body.missing_context,
        notes=body.notes,
        submitted_at=submitted_at,
    )
    session.add(row)

    # Write immutable AuditEvent
    session.add(
        AuditEvent(
            id=str(uuid.uuid4()),
            event_id=event_id,
            action="feedback_submitted",
            actor=actor.email,
            actor_role=actor_role,
            occurred_at=submitted_at,
            details_json=json.dumps(
                {
                    "feedback_id": row.id,
                    "recommendation_useful": body.recommendation_useful,
                    "recommendation_accurate": body.recommendation_accurate,
                    "outcome": body.outcome,
                    "missing_context_provided": body.missing_context is not None,
                    "notes_provided": body.notes is not None,
                }
            ),
        )
    )

    await session.flush()

    logger.info(
        "feedback.submitted",
        event_id=event_id,
        feedback_id=row.id,
        outcome=body.outcome,
        actor=actor.email,
    )

    return _row_to_response(row)


# ---------------------------------------------------------------------------
# GET /api/v1/events/{event_id}/feedback — retrieve all
# ---------------------------------------------------------------------------


@router.get(
    "/{event_id}/feedback",
    response_model=FeedbackListResponse,
    summary="Retrieve all feedback for a security event",
    dependencies=[Depends(require_permission("events:read"))],
    responses={
        200: {"description": "Feedback list returned"},
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
        404: {"description": "Event not found"},
    },
)
async def get_feedback(
    event_id: str,
    session: AsyncSession = Depends(get_db),
) -> FeedbackListResponse:
    """
    Return all feedback records for a security event, newest first.

    Returns an empty list (not 404) if the event exists but has no feedback.
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

    stmt = (
        select(Feedback).where(Feedback.event_id == event_id).order_by(Feedback.submitted_at.desc())
    )
    rows = list((await session.execute(stmt)).scalars().all())

    return FeedbackListResponse(
        event_id=event_id,
        items=[_row_to_response(r) for r in rows],
        total=len(rows),
    )
