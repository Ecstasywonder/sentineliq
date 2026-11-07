"""
Event Ingestion & Queue API — Gates 5 & 8.

Routes:
    POST   /api/v1/events                  Ingest a security event
    GET    /api/v1/events                  Paginated event queue
    GET    /api/v1/events/{id}             Retrieve single event
    PATCH  /api/v1/events/{id}/status      Lifecycle transition
    POST   /api/v1/events/{id}/assess      Run deterministic assessment (Gate 8)

Design notes:
- Deduplication: if provider_event_id is set and an event with that ID
  arrived within settings.event_dedup_window_seconds, return the existing
  event with HTTP 200 (not 201) and a Duplicate-Event: true header.
- Normalisation: raw_metadata dict is serialised to JSON and stored.
  event_timestamp is passed through as-is (validated by Pydantic).
  Status advances RECEIVED → NORMALISED on successful persist.
- The /assess endpoint orchestrates the full deterministic pipeline:
  EvidenceAggregator → RiskEngine → ConfidenceEngine → persist → state change.
  LLM is NOT called here (Gate 14+).
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
from app.models.audit import AuditEvent
from app.models.event import SecurityEvent
from app.schemas.assessment import (
    AssessEventRequest,
    AssessmentFactorsResponse,
    AssessmentResponse,
    AssessmentRetrievalResponse,
    ConfidenceReductionDetail,
    RiskFactorDetail,
)
from app.schemas.context import ContextResultDetail
from app.schemas.events import (
    VALID_STATUSES,
    ErrorDetail,
    EventIngestRequest,
    EventListResponse,
    EventResponse,
)
from app.schemas.explanation import ExplanationResultDetail
from app.schemas.triage import TriageResultDetail
from app.security.dependencies import AuthenticatedUser, require_permission
from app.services.assessment_service import AssessmentService
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
    dependencies=[Depends(require_permission("events:ingest"))],
    responses={
        201: {"description": "Event created and normalised"},
        200: {"description": "Duplicate event — returning existing record"},
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
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
        raw_metadata_json = json.dumps(
            payload.raw_metadata,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )

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
    dependencies=[Depends(require_permission("events:read"))],
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
    operation_id="get_event_detail",
    response_model=EventResponse,
    summary="Retrieve a single security event",
    dependencies=[Depends(require_permission("events:read"))],
    responses={
        200: {"description": "Event found"},
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
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


_DECISION_ONLY_STATUSES = frozenset(
    {
        "awaiting_review",
        "context_incomplete",
        "escalated",
        "closed",
        "dismissed",
    }
)


@router.patch(
    "/{event_id}/status",
    response_model=EventResponse,
    summary="Advance event lifecycle status",
    responses={
        200: {"description": "Status updated"},
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
        404: {"description": "Event not found"},
        409: {"description": "Invalid transition"},
        422: {"description": "Unknown status"},
    },
)
async def update_event_status(
    event_id: str,
    body: StatusTransitionRequest,
    session: AsyncSession = Depends(get_db),
    actor: AuthenticatedUser = Depends(require_permission("events:decide")),
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

    if body.status in _DECISION_ONLY_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=ErrorDetail(
                code="DECISION_REQUIRED",
                message=(
                    f"Status '{body.status}' is controlled by the assessment, decision, "
                    "or escalation workflow and cannot be set directly."
                ),
            ).model_dump(),
        )

    prior_status = event.status
    event.status = body.status
    session.add(
        AuditEvent(
            id=_new_id(),
            event_id=event_id,
            action="event_status_transitioned",
            actor=actor.email,
            actor_role=actor.roles[0] if actor.roles else "unknown",
            occurred_at=_now_iso(),
            details_json=json.dumps(
                {
                    "prior_status": prior_status,
                    "target_status": body.status,
                    "reason": body.reason,
                    "route": "PATCH /events/{id}/status",
                }
            ),
        )
    )
    await session.flush()

    logger.info(
        "events.status_updated",
        event_id=event_id,
        new_status=body.status,
    )

    return EventResponse.from_orm_event(event)


# ---------------------------------------------------------------------------
# POST /api/v1/events/{event_id}/assess — Gate 8 assessment
# ---------------------------------------------------------------------------


@router.post(
    "/{event_id}/assess",
    response_model=None,
    status_code=200,
    summary="Run deterministic risk & confidence assessment",
    dependencies=[Depends(require_permission("events:decide"))],
    responses={
        200: {"description": "Assessment complete — returns AssessmentResponse"},
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
        404: {"description": "Event not found"},
        409: {"description": "Event cannot be assessed from its current status"},
        422: {"description": "Validation error"},
        500: {"description": "Internal server error"},
    },
)
async def assess_event(
    event_id: str,
    body: AssessEventRequest | None = None,
    session: AsyncSession = Depends(get_db),
) -> AssessmentResponse:
    """
    Trigger the full deterministic assessment pipeline for a security event.

    1. Validates the event exists and is in an assessable state.
    2. Gathers evidence from all 6 context sources (EvidenceAggregator).
    3. Runs the deterministic RiskEngine (ADR-003 — no LLM involvement).
    4. Runs the independent ConfidenceEngine (ADR-004).
    5. Persists RiskAssessment + ConfidenceAssessment rows.
    6. Denormalises risk/confidence scores onto SecurityEvent.
    7. Advances event status: normalised → assessing → awaiting_review.

    Returns the full AssessmentResponse bundle.
    """
    payload = body or AssessEventRequest()

    try:
        service = AssessmentService(session)
        result = await service.run(
            event_id,
            unavailable_source_ids=payload.unavailable_source_ids,
            policy_version=payload.policy_version,
        )
    except ValueError as exc:
        # Event not found or already terminal
        msg = str(exc)
        status_code = 404 if "not found" in msg.lower() else 409
        raise HTTPException(
            status_code=status_code,
            detail=ErrorDetail(
                code="ASSESSMENT_ERROR",
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

    logger.info(
        "events.assess.complete",
        event_id=event_id,
        risk_score=result.risk_score,
        risk_level=result.risk_level,
        confidence_score=result.confidence_score,
    )

    return result


# ---------------------------------------------------------------------------
# GET /api/v1/events/{event_id}/assessment — Gate 9 retrieval
# ---------------------------------------------------------------------------


@router.get(
    "/{event_id}/assessment",
    response_model=AssessmentRetrievalResponse,
    summary="Retrieve persisted risk & confidence assessment",
    dependencies=[Depends(require_permission("events:read"))],
    responses={
        200: {"description": "Assessment found"},
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
        404: {"description": "Event or assessment not found"},
    },
)
async def get_assessment(
    event_id: str,
    session: AsyncSession = Depends(get_db),
) -> AssessmentRetrievalResponse:
    """
    Retrieve the persisted assessment for a security event.

    Returns the full risk & confidence breakdown stored after
    ``POST /events/{id}/assess`` was called.  The response is built
    from the ``risk_assessments`` and ``confidence_assessments`` DB rows —
    no re-computation occurs.

    Returns 404 if the event does not exist or has never been assessed.
    """
    import json as _json

    from sqlalchemy import select

    from app.models.assessment import ConfidenceAssessment, RiskAssessment
    from app.models.recommendation import Recommendation

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

    # Load risk assessment row
    stmt = select(RiskAssessment).where(RiskAssessment.event_id == event_id)
    result = await session.execute(stmt)
    risk_row: RiskAssessment | None = result.scalar_one_or_none()
    if risk_row is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorDetail(
                code="ASSESSMENT_NOT_FOUND",
                message=f"No assessment found for event '{event_id}'. "
                "Run POST /events/{id}/assess first.",
            ).model_dump(),
        )

    # Load confidence assessment row
    conf_stmt = select(ConfidenceAssessment).where(ConfidenceAssessment.event_id == event_id)
    conf_result = await session.execute(conf_stmt)
    conf_row: ConfidenceAssessment | None = conf_result.scalar_one_or_none()
    recommendation_result = await session.execute(
        select(Recommendation).where(Recommendation.event_id == event_id)
    )
    recommendation = recommendation_result.scalar_one_or_none()

    # Deserialise stored factor JSON
    risk_factors: list[RiskFactorDetail] = []
    if risk_row.risk_factors_json:
        try:
            for f in _json.loads(risk_row.risk_factors_json):
                risk_factors.append(RiskFactorDetail(**f))
        except (ValueError, KeyError):
            pass  # degrade gracefully — DB row may predate schema change

    # Deserialise stored confidence reductions JSON
    conf_reductions: list[ConfidenceReductionDetail] = []
    if conf_row and conf_row.reductions_json:
        try:
            for r in _json.loads(conf_row.reductions_json):
                conf_reductions.append(ConfidenceReductionDetail(**r))
        except (ValueError, KeyError):
            pass

    def _load_snapshot(raw: str | None, schema):
        if not raw:
            return None
        try:
            return schema(**_json.loads(raw))
        except (TypeError, ValueError, KeyError):
            return None

    triage = _load_snapshot(risk_row.triage_result_json, TriageResultDetail)
    context = _load_snapshot(risk_row.context_result_json, ContextResultDetail)
    explanation = _load_snapshot(
        risk_row.explanation_result_json,
        ExplanationResultDetail,
    )
    try:
        evidence_errors = _json.loads(risk_row.evidence_errors_json or "{}")
    except (TypeError, ValueError):
        evidence_errors = {}
    try:
        workflow_state = _json.loads(risk_row.workflow_state_json or "{}")
    except (TypeError, ValueError):
        workflow_state = {}

    return AssessmentRetrievalResponse(
        assessment_id=risk_row.id,
        event_id=event_id,
        risk_policy_version=risk_row.risk_policy_version,
        risk_score=risk_row.risk_score,
        risk_level=risk_row.risk_level,
        risk_factors=risk_factors,
        confidence_score=conf_row.confidence_score
        if conf_row
        else risk_row.confidence_score or 0.0,
        confidence_level=conf_row.confidence_level
        if conf_row
        else risk_row.confidence_level or "low",
        confidence_reductions=conf_reductions,
        sources_available=conf_row.sources_available if conf_row else 0,
        sources_required=conf_row.sources_required if conf_row else 0,
        triage=triage,
        context=context,
        explanation=explanation,
        recommendation_id=recommendation.id if recommendation else None,
        recommendation=(
            AssessmentService._recommendation_detail(recommendation)
            if recommendation is not None
            else None
        ),
        evidence_errors=evidence_errors,
        workflow_state=workflow_state,
        assessed_at=risk_row.assessed_at,
        agent_run_id=risk_row.agent_run_id,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/events/{event_id}/assessment/factors — Gate 9 factor breakdown
# ---------------------------------------------------------------------------


@router.get(
    "/{event_id}/assessment/factors",
    response_model=AssessmentFactorsResponse,
    summary="Per-factor risk breakdown for a persisted assessment",
    dependencies=[Depends(require_permission("events:read"))],
    responses={
        200: {"description": "Factor breakdown found"},
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
        404: {"description": "Event or assessment not found"},
    },
)
async def get_assessment_factors(
    event_id: str,
    session: AsyncSession = Depends(get_db),
) -> AssessmentFactorsResponse:
    """
    Return the per-factor risk breakdown for a security event's latest assessment.

    This is a focused view of the same data returned by
    ``GET /events/{id}/assessment``, limited to the risk factors only —
    useful for UI panels that only need to display the factor contribution
    bars without the full confidence/evidence context.

    Returns 404 if the event does not exist or has never been assessed.
    """
    import json as _json

    from sqlalchemy import select

    from app.models.assessment import RiskAssessment

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

    # Load risk assessment row
    stmt = select(RiskAssessment).where(RiskAssessment.event_id == event_id)
    result = await session.execute(stmt)
    risk_row: RiskAssessment | None = result.scalar_one_or_none()
    if risk_row is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorDetail(
                code="ASSESSMENT_NOT_FOUND",
                message=f"No assessment found for event '{event_id}'. "
                "Run POST /events/{id}/assess first.",
            ).model_dump(),
        )

    # Deserialise stored factor JSON
    factors: list[RiskFactorDetail] = []
    if risk_row.risk_factors_json:
        try:
            for f in _json.loads(risk_row.risk_factors_json):
                factors.append(RiskFactorDetail(**f))
        except (ValueError, KeyError):
            pass  # degrade gracefully

    return AssessmentFactorsResponse(
        assessment_id=risk_row.id,
        event_id=event_id,
        risk_policy_version=risk_row.risk_policy_version,
        risk_score=risk_row.risk_score,
        risk_level=risk_row.risk_level,
        factors=factors,
        assessed_at=risk_row.assessed_at,
    )
