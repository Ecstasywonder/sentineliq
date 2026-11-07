"""
Coordinator API — Gate 17.

Routes:
    GET  /api/v1/events/{event_id}/review   Trigger a Coordinator read-only review

Design notes:
- The Coordinator is read-only: it never changes event state, scores risk,
  or makes an operational decision (ADR-006, master prompt §14).
- Events must have status awaiting_review or escalated to be reviewable.
- human_review_required is ALWAYS True in the response.
- The AgentRun row is persisted for observability (master prompt §34).
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.event import SecurityEvent
from app.schemas.coordinator import CoordinatorReviewResponse
from app.security.dependencies import AuthenticatedUser, require_permission
from app.services.coordinator_service import CoordinatorService

logger = structlog.get_logger(__name__)

router = APIRouter()

# Statuses from which a coordinator review is meaningful
_REVIEWABLE_STATUSES = frozenset({"awaiting_review", "escalated"})


@router.get(
    "/{event_id}/review",
    response_model=CoordinatorReviewResponse,
    status_code=200,
    summary="Trigger a Sentinel Coordinator read-only review",
    responses={
        200: {"description": "Coordinator review completed"},
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
        404: {"description": "Event not found"},
        409: {"description": "Event not in a reviewable status"},
        422: {"description": "Validation error"},
    },
)
async def get_coordinator_review(
    event_id: str,
    db: AsyncSession = Depends(get_db),
    _: AuthenticatedUser = Depends(require_permission("events:read")),
) -> CoordinatorReviewResponse:
    """
    Request a read-only Coordinator review of an assessed security event.

    The Coordinator delegates to the Triage, Context, and Explanation specialist
    agents and returns a structured review. It NEVER changes event state or
    produces an operational decision. Human review remains mandatory.

    Only events in ``awaiting_review`` or ``escalated`` status may be reviewed.
    """
    # --- Load event -----------------------------------------------------------
    result = await db.execute(
        select(SecurityEvent).where(SecurityEvent.id == event_id)
    )
    event: SecurityEvent | None = result.scalar_one_or_none()

    if event is None:
        raise HTTPException(status_code=404, detail=f"Event '{event_id}' not found.")

    if event.status not in _REVIEWABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Event '{event_id}' is in status '{event.status}'. "
                f"A Coordinator review requires status "
                f"{sorted(_REVIEWABLE_STATUSES)}."
            ),
        )

    # --- Run Coordinator review -----------------------------------------------
    svc = CoordinatorService(db)
    review = await svc.run(event_id)

    return CoordinatorReviewResponse(
        event_id=review.event_id,
        assessment_ready=review.assessment_ready,
        summary=review.summary,
        missing_evidence=review.missing_evidence,
        human_review_required=review.human_review_required,
        source=review.source,
        agent_run_id=review.agent_run_id,
    )
