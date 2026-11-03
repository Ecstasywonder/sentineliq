"""
Event Ingestion & Queue API — Gate 5.

Routes:
    POST   /api/v1/events          Ingest a security event
    GET    /api/v1/events          Paginated event queue
    GET    /api/v1/events/{id}     Retrieve single event

Design notes:
- Deduplication: if provider_event_id is set and an event with that ID
  arrived within settings.event_dedup_window_seconds, return the existing
  event with HTTP 200 (not 201) and a Duplicate-Event: true header.
- Normalisation: raw_metadata dict is serialised to JSON and stored.
  event_timestamp is passed through as-is (validated by Pydantic).
  Status advances RECEIVED → NORMALISED on successful persist.
- The endpoint does NOT trigger agent assessment — that is Gate 7.
  Status is left at NORMALISED after ingestion.
- All DB errors propagate as HTTP 500; structured error body returned.
"""

from __future__ import annotations

import json
import math
import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.event import SecurityEvent
from app.schemas.events import (
    VALID_STATUSES,
    ErrorDetail,
    EventIngestRequest,
    EventListResponse,
    EventResponse,
)
from app.services.event_lifecycle import InvalidTransitionError, validate_transition

logger = structlog.get_logger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


async def _find_duplicate(
    session: AsyncSession,
    provider_event_id: str,
    dedup_window_seconds: int,
) -> SecurityEvent | None:
    """
    Return an existing SecurityEvent if provider_event_id was already received
    within the deduplication window, else None.

    The window check is done in Python (not SQL) to stay compatible with both
    PostgreSQL and the SQLite in-memory test database.
    """
    stmt = (
        select(SecurityEvent)
        .where(SecurityEvent.provider_event_id == provider_event_id)
        .order_by(SecurityEvent.created_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    existing: SecurityEvent | None = result.scalar_one_or_none()
    if existing is None:
        return None

    # Check window
    try:
        created = existing.created_at
        if created is not None:
            now = datetime.now(UTC)
            # created_at may be timezone-naive from SQLite
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            age_seconds = (now - created).total_seconds()
            if age_seconds <= dedup_window_seconds:
                return existing
    except Exception:
        pass  # If we can't parse, treat as non-duplicate

    return None


# ---------------------------------------------------------------------------
# POST /api/v1/events — ingest
# ---------------------------------------------------------------------------


@router.post(
    "",
    status_code=201,
    response_model=EventResponse,
    summary="Ingest a security event",
    responses={
        201: {"description": "Event created and normalised"},
        200: {"description": "Duplicate event — returning existing record"},
        422: {"description": "Validation error"},
        500: {"description": "Internal server error"},
    },
)
async def ingest_event(
    payload: EventIngestRequest,
    response: Response,
    session: AsyncSession = Depends(get_db),
) -> EventResponse:
    """
    Ingest a security event from a detection system or simulator.

    - Validates and normalises the payload.
    - Deduplicates against existing events by ``provider_event_id``.
    - Persists the event at status ``normalised``.
    - Returns HTTP 201 for a new event, HTTP 200 for a duplicate (with
      ``Duplicate-Event: true`` header).
    """
    from app.config import get_settings

    settings = get_settings()

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------
    if payload.provider_event_id:
        duplicate = await _find_duplicate(
            session,
            payload.provider_event_id,
            settings.event_dedup_window_seconds,
        )
        if duplicate is not None:
            logger.info(
                "events.ingest.duplicate",
                provider_event_id=payload.provider_event_id,
                existing_id=duplicate.id,
            )
            response.status_code = 200
            response.headers["Duplicate-Event"] = "true"
            return EventResponse.from_orm_event(duplicate)

    # ------------------------------------------------------------------
    # Normalise
    # ------------------------------------------------------------------
    raw_metadata_json: str | None = None
    if payload.raw_metadata is not None:
        raw_metadata_json = json.dumps(payload.raw_metadata)

    normalised_data = json.dumps(
        {
            "event_type": payload.event_type,
            "event_timestamp": payload.event_timestamp,
            "location_id": payload.location_id,
            "facility_id": payload.facility_id,
            "camera_id": payload.camera_id,
            "zone": payload.zone,
            "detector_confidence": payload.detector_confidence,
            "source_adapter": payload.source_adapter,
            "normalised_at": _now_iso(),
        }
    )

    # ------------------------------------------------------------------
    # Persist — status: received → normalised
    # ------------------------------------------------------------------
    event = SecurityEvent(
        id=_new_id(),
        provider_event_id=payload.provider_event_id,
        source_adapter=payload.source_adapter,
        event_type=payload.event_type,
        event_timestamp=payload.event_timestamp,
        location_id=payload.location_id,
        facility_id=payload.facility_id,
        camera_id=payload.camera_id,
        zone=payload.zone,
        detector_confidence=payload.detector_confidence,
        thumbnail_url=payload.thumbnail_url,
        raw_metadata=raw_metadata_json,
        normalised_data=normalised_data,
        status="normalised",
    )
    session.add(event)
    await session.flush()  # get DB-generated timestamps

    logger.info(
        "events.ingest.created",
        event_id=event.id,
        event_type=event.event_type,
        location_id=event.location_id,
        source_adapter=event.source_adapter,
    )

    return EventResponse.from_orm_event(event)


# ---------------------------------------------------------------------------
# GET /api/v1/events — paginated queue
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=EventListResponse,
    summary="List security events (event queue)",
)
async def list_events(
    status: str | None = Query(
        default=None,
        description=f"Filter by status. Valid: {sorted(VALID_STATUSES)}",
    ),
    risk_level: str | None = Query(
        default=None,
        description="Filter by risk level: low | medium | high | critical",
    ),
    page: int = Query(default=1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    session: AsyncSession = Depends(get_db),
) -> EventListResponse:
    """
    Return a paginated list of security events, ordered by risk priority then time.

    - ``status`` filters to a single lifecycle status.
    - ``risk_level`` filters to a single risk level.
    - Results are ordered: CRITICAL → HIGH → MEDIUM → LOW, then by
      ``event_timestamp`` descending within each level.
    """
    # ------------------------------------------------------------------
    # Validate query params
    # ------------------------------------------------------------------
    if status is not None and status not in VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=ErrorDetail(
                code="INVALID_STATUS",
                message=f"Unknown status '{status}'.",
                detail=f"Valid statuses: {sorted(VALID_STATUSES)}",
            ).model_dump(),
        )

    valid_risk_levels = {"low", "medium", "high", "critical"}
    if risk_level is not None and risk_level not in valid_risk_levels:
        raise HTTPException(
            status_code=422,
            detail=ErrorDetail(
                code="INVALID_RISK_LEVEL",
                message=f"Unknown risk_level '{risk_level}'.",
                detail=f"Valid levels: {sorted(valid_risk_levels)}",
            ).model_dump(),
        )

    # ------------------------------------------------------------------
    # Build query
    # ------------------------------------------------------------------
    base_stmt = select(SecurityEvent)
    count_stmt = select(func.count()).select_from(SecurityEvent)

    if status is not None:
        base_stmt = base_stmt.where(SecurityEvent.status == status)
        count_stmt = count_stmt.where(SecurityEvent.status == status)
    if risk_level is not None:
        base_stmt = base_stmt.where(SecurityEvent.risk_level == risk_level)
        count_stmt = count_stmt.where(SecurityEvent.risk_level == risk_level)

    # Risk-priority ordering (CRITICAL first) using a CASE expression
    # SQLAlchemy text() keeps it simple and db-portable
    from sqlalchemy import case

    risk_order = case(
        (SecurityEvent.risk_level == "critical", 1),
        (SecurityEvent.risk_level == "high", 2),
        (SecurityEvent.risk_level == "medium", 3),
        (SecurityEvent.risk_level == "low", 4),
        else_=5,
    )

    base_stmt = (
        base_stmt.order_by(risk_order, SecurityEvent.event_timestamp.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    total_result = await session.execute(count_stmt)
    total: int = total_result.scalar_one()

    events_result = await session.execute(base_stmt)
    events = list(events_result.scalars().all())

    pages = max(1, math.ceil(total / page_size))

    return EventListResponse(
        items=[EventResponse.from_orm_event(e) for e in events],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/events/{event_id} — single event
# ---------------------------------------------------------------------------


@router.get(
    "/{event_id}",
    response_model=EventResponse,
    summary="Retrieve a single security event",
    responses={
        200: {"description": "Event found"},
        404: {"description": "Event not found"},
    },
)
async def get_event(
    event_id: str,
    session: AsyncSession = Depends(get_db),
) -> EventResponse:
    """Retrieve a single security event by its ID."""
    result = await session.get(SecurityEvent, event_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorDetail(
                code="EVENT_NOT_FOUND",
                message=f"Event '{event_id}' not found.",
            ).model_dump(),
        )
    return EventResponse.from_orm_event(result)


# ---------------------------------------------------------------------------
# PATCH /api/v1/events/{event_id}/status — lifecycle transition
# ---------------------------------------------------------------------------


class StatusTransitionRequest(BaseModel):
    status: str
    reason: str | None = None


@router.patch(
    "/{event_id}/status",
    response_model=EventResponse,
    summary="Advance event lifecycle status",
    responses={
        200: {"description": "Status updated"},
        404: {"description": "Event not found"},
        409: {"description": "Invalid transition"},
        422: {"description": "Unknown status"},
    },
)
async def update_event_status(
    event_id: str,
    body: StatusTransitionRequest,
    session: AsyncSession = Depends(get_db),
) -> EventResponse:
    """
    Advance a security event to a new lifecycle status.

    Only valid transitions (per the state machine) are accepted.
    Invalid transitions return HTTP 409.
    """
    if body.status not in VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=ErrorDetail(
                code="INVALID_STATUS",
                message=f"Unknown status '{body.status}'.",
            ).model_dump(),
        )

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
        validate_transition(event.status, body.status)
    except InvalidTransitionError as exc:
        raise HTTPException(
            status_code=409,
            detail=ErrorDetail(
                code="INVALID_TRANSITION",
                message=str(exc),
            ).model_dump(),
        ) from exc

    event.status = body.status
    await session.flush()

    logger.info(
        "events.status_updated",
        event_id=event_id,
        new_status=body.status,
    )

    return EventResponse.from_orm_event(event)
