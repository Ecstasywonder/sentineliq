"""
Gate 7 — Context Tool endpoints.

All endpoints are read-only (ADR-005) and require the ``tools:read`` permission.
They include the human-facing evidence APIs plus compact event-bound façades
available to watsonx Orchestrate agents.

Routes
------
GET /api/v1/tools/access-events        -- badge events near an event location
GET /api/v1/tools/schedule             -- schedule context
GET /api/v1/tools/work-orders          -- active work orders
GET /api/v1/tools/delivery             -- delivery windows
GET /api/v1/tools/location-policy      -- security rules for a location
GET /api/v1/tools/incident-history     -- recent historical incidents
GET /api/v1/tools/integration-health   -- adapter health status
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.integrations.access_control import MockAccessControlAdapter
from app.integrations.delivery import MockDeliveryAdapter
from app.integrations.schedule import MockScheduleAdapter
from app.integrations.work_order import MockWorkOrderAdapter
from app.models.assessment import RiskAssessment
from app.models.event import SecurityEvent
from app.models.incident import IncidentHistory
from app.models.integration import IntegrationHealth
from app.models.recommendation import Recommendation
from app.models.security_rule import SecurityRule
from app.schemas.explanation import AssessmentBundleResponse
from app.schemas.knowledge import KnowledgeSearchResponse
from app.schemas.tools import (
    AccessEventRecord,
    AccessEventsResponse,
    AgentAccessFact,
    AgentAccessResponse,
    AgentAssessmentResponse,
    AgentCameraMetadataResponse,
    AgentDeliveryFact,
    AgentDeliveryResponse,
    AgentEventDetailResponse,
    AgentIncidentFact,
    AgentIncidentResponse,
    AgentIntegrationFact,
    AgentIntegrationResponse,
    AgentPolicyFact,
    AgentPolicyResponse,
    AgentScheduleFact,
    AgentScheduleResponse,
    AgentToolMeta,
    AgentWorkOrderFact,
    AgentWorkOrdersResponse,
    DeliveryRecord,
    DeliveryResponse,
    IncidentHistoryResponse,
    IncidentRecord,
    IntegrationHealthRecord,
    IntegrationHealthResponse,
    LocationPolicyResponse,
    ScheduleRecord,
    ScheduleResponse,
    SecurityRuleRecord,
    ToolMeta,
    WorkOrderRecord,
    WorkOrdersResponse,
)
from app.security.dependencies import get_current_human_user, require_permission
from app.services.knowledge_retrieval import KnowledgeRetrievalService

router = APIRouter()

_PERM = "tools:read"
_MAX_LIMIT = 200
_AGENT_MAX_RECORDS = 20
_HUMAN_TOOL_DEPENDENCIES = [
    Depends(require_permission(_PERM)),
    Depends(get_current_human_user),
]


def _json_object(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _json_list(raw: str | None) -> list[dict]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return []
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _json_string_list(raw: str | None) -> list[str]:
    """Return only string values from a persisted JSON array."""
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return []
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


# ---------------------------------------------------------------------------
# 1. Access Events
# ---------------------------------------------------------------------------


@router.get(
    "/assessment-bundle",
    operation_id="get_assessment_bundle",
    response_model=AssessmentBundleResponse,
    summary="Retrieve the persisted assessment reconstruction bundle",
    dependencies=_HUMAN_TOOL_DEPENDENCIES,
)
async def get_assessment_bundle(
    event_id: str = Query(..., max_length=36),
    session: AsyncSession = Depends(get_db),
) -> AssessmentBundleResponse:
    event = await session.get(SecurityEvent, event_id)
    assessment_result = await session.execute(
        select(RiskAssessment).where(RiskAssessment.event_id == event_id)
    )
    assessment = assessment_result.scalar_one_or_none()
    if event is None or assessment is None:
        raise HTTPException(status_code=404, detail="Assessment bundle not found.")
    recommendation_result = await session.execute(
        select(Recommendation).where(Recommendation.event_id == event_id)
    )
    recommendation = recommendation_result.scalar_one_or_none()

    return AssessmentBundleResponse(
        event_id=event_id,
        event_status=event.status,
        risk_score=assessment.risk_score,
        risk_level=assessment.risk_level,
        risk_policy_version=assessment.risk_policy_version,
        risk_factors=_json_list(assessment.risk_factors_json),
        confidence_score=assessment.confidence_score,
        confidence_level=assessment.confidence_level,
        triage=_json_object(assessment.triage_result_json),
        context=_json_object(assessment.context_result_json),
        explanation=_json_object(assessment.explanation_result_json),
        recommendation_id=recommendation.id if recommendation else None,
        recommendation=(
            {
                "id": recommendation.id,
                "summary": recommendation.summary,
                "recommended_action": recommendation.recommended_action,
                "why": _json_list(recommendation.why_json),
                "missing_evidence": _json_string_list(recommendation.missing_evidence_json),
                "limitations": _json_string_list(recommendation.limitations_json),
                "requires_human_review": recommendation.requires_human_review,
                "risk_level": recommendation.risk_level,
                "risk_score": recommendation.risk_score,
                "confidence_score": recommendation.confidence_score,
                "agent_run_id": recommendation.agent_run_id,
                "generated_at": recommendation.generated_at,
            }
            if recommendation is not None
            else {}
        ),
        evidence_errors={
            str(key): str(value)
            for key, value in _json_object(assessment.evidence_errors_json).items()
        },
        workflow_state=_json_object(assessment.workflow_state_json),
        assessed_at=assessment.assessed_at,
    )


@router.get(
    "/access-events",
    operation_id="get_access_events",
    response_model=AccessEventsResponse,
    summary="Badge / access-control events for a location",
    dependencies=_HUMAN_TOOL_DEPENDENCIES,
)
async def get_access_events(
    location_id: str = Query(..., description="Location identifier to filter by"),
    facility_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=_MAX_LIMIT),
    session: AsyncSession = Depends(get_db),
) -> AccessEventsResponse:
    adapter = MockAccessControlAdapter(session)
    raw = await adapter.get_access_events(location_id, facility_id=facility_id, limit=limit)
    records = [AccessEventRecord(**r) for r in raw]
    return AccessEventsResponse(
        meta=ToolMeta(
            source=adapter.source_id,
            record_count=len(records),
            truncated=len(records) == limit,
        ),
        records=records,
    )


# ---------------------------------------------------------------------------
# 2. Schedule
# ---------------------------------------------------------------------------


@router.get(
    "/schedule",
    operation_id="get_schedule",
    response_model=ScheduleResponse,
    summary="Schedule context for a location or facility",
    dependencies=_HUMAN_TOOL_DEPENDENCIES,
)
async def get_schedule(
    location_id: str | None = Query(None),
    facility_id: str | None = Query(None),
    schedule_type: str | None = Query(None),
    limit: int = Query(50, ge=1, le=_MAX_LIMIT),
    session: AsyncSession = Depends(get_db),
) -> ScheduleResponse:
    adapter = MockScheduleAdapter(session)
    raw = await adapter.get_schedule(
        location_id, facility_id=facility_id, schedule_type=schedule_type, limit=limit
    )
    records = [ScheduleRecord(**r) for r in raw]
    return ScheduleResponse(
        meta=ToolMeta(
            source=adapter.source_id,
            record_count=len(records),
            truncated=len(records) == limit,
        ),
        records=records,
    )


# ---------------------------------------------------------------------------
# 3. Work Orders
# ---------------------------------------------------------------------------


@router.get(
    "/work-orders",
    operation_id="get_work_orders",
    response_model=WorkOrdersResponse,
    summary="Active work orders for a location",
    dependencies=_HUMAN_TOOL_DEPENDENCIES,
)
async def get_work_orders(
    location_id: str = Query(..., description="Location identifier to filter by"),
    facility_id: str | None = Query(None),
    status: str | None = Query(None, description="Filter by work-order status"),
    limit: int = Query(50, ge=1, le=_MAX_LIMIT),
    session: AsyncSession = Depends(get_db),
) -> WorkOrdersResponse:
    adapter = MockWorkOrderAdapter(session)
    raw = await adapter.get_work_orders(
        location_id, facility_id=facility_id, status=status, limit=limit
    )
    records = [WorkOrderRecord(**r) for r in raw]
    return WorkOrdersResponse(
        meta=ToolMeta(
            source=adapter.source_id,
            record_count=len(records),
            truncated=len(records) == limit,
        ),
        records=records,
    )


# ---------------------------------------------------------------------------
# 4. Delivery
# ---------------------------------------------------------------------------


@router.get(
    "/delivery",
    operation_id="get_delivery",
    response_model=DeliveryResponse,
    summary="Delivery schedule for a location",
    dependencies=_HUMAN_TOOL_DEPENDENCIES,
)
async def get_delivery(
    location_id: str = Query(..., description="Location identifier to filter by"),
    facility_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=_MAX_LIMIT),
    session: AsyncSession = Depends(get_db),
) -> DeliveryResponse:
    adapter = MockDeliveryAdapter(session)
    raw = await adapter.get_deliveries(location_id, facility_id=facility_id, limit=limit)
    records = [DeliveryRecord(**r) for r in raw]
    return DeliveryResponse(
        meta=ToolMeta(
            source=adapter.source_id,
            record_count=len(records),
            truncated=len(records) == limit,
        ),
        records=records,
    )


# ---------------------------------------------------------------------------
# 5. Location Policy
# ---------------------------------------------------------------------------


@router.get(
    "/location-policy",
    operation_id="get_location_policy",
    response_model=LocationPolicyResponse,
    summary="Active security rules for a location",
    dependencies=_HUMAN_TOOL_DEPENDENCIES,
)
async def get_location_policy(
    location_id: str = Query(..., description="Location identifier"),
    facility_id: str | None = Query(None),
    session: AsyncSession = Depends(get_db),
) -> LocationPolicyResponse:
    stmt = (
        select(SecurityRule)
        .where(SecurityRule.is_active.is_(True))
        .where((SecurityRule.location_id == location_id) | (SecurityRule.location_id.is_(None)))
    )
    if facility_id:
        stmt = stmt.where(
            (SecurityRule.facility_id == facility_id) | (SecurityRule.facility_id.is_(None))
        )
    result = await session.execute(stmt)
    rows = result.scalars().all()
    records = [
        SecurityRuleRecord(
            id=str(r.id),
            facility_id=r.facility_id,
            location_id=r.location_id,
            rule_code=r.rule_code,
            rule_type=r.rule_type,
            description=r.description,
            restricted_after=r.restricted_after,
            restricted_before=r.restricted_before,
            applies_to_zones=r.applies_to_zones,
            is_active=r.is_active,
            policy_reference=r.policy_reference,
        )
        for r in rows
    ]
    return LocationPolicyResponse(
        meta=ToolMeta(source="db_security_rules", record_count=len(records)),
        records=records,
    )


# ---------------------------------------------------------------------------
# 6. Incident History
# ---------------------------------------------------------------------------


@router.get(
    "/incident-history",
    operation_id="get_incident_history",
    response_model=IncidentHistoryResponse,
    summary="Historical security incidents at a location",
    dependencies=_HUMAN_TOOL_DEPENDENCIES,
)
async def get_incident_history(
    location_id: str = Query(..., description="Location identifier"),
    facility_id: str | None = Query(None),
    limit: int = Query(20, ge=1, le=_MAX_LIMIT),
    session: AsyncSession = Depends(get_db),
) -> IncidentHistoryResponse:
    stmt = (
        select(IncidentHistory)
        .where(IncidentHistory.location_id == location_id)
        .order_by(IncidentHistory.occurred_at.desc())
        .limit(limit)
    )
    if facility_id:
        stmt = stmt.where(IncidentHistory.facility_id == facility_id)
    result = await session.execute(stmt)
    rows = result.scalars().all()
    records = [
        IncidentRecord(
            id=str(r.id),
            facility_id=r.facility_id,
            location_id=r.location_id,
            incident_code=r.incident_code,
            incident_type=r.incident_type,
            severity=r.severity,
            occurred_at=r.occurred_at,
            description=r.description,
            outcome=r.outcome,
            resolved=r.resolved,
            resolution_notes=r.resolution_notes,
        )
        for r in rows
    ]
    return IncidentHistoryResponse(
        meta=ToolMeta(
            source="db_incident_history",
            record_count=len(records),
            truncated=len(records) == limit,
        ),
        records=records,
    )


# ---------------------------------------------------------------------------
# 6b. Hybrid incident / policy knowledge search (Gate 8)
# ---------------------------------------------------------------------------


@router.get(
    "/knowledge-search",
    operation_id="search_knowledge",
    response_model=KnowledgeSearchResponse,
    summary="Hybrid semantic and metadata search over incidents and policies",
    dependencies=_HUMAN_TOOL_DEPENDENCIES,
)
async def search_knowledge(
    q: str = Query(..., min_length=2, max_length=500, description="Natural-language query"),
    facility_id: str | None = Query(None, max_length=36),
    location_id: str | None = Query(None, max_length=128),
    event_type: str | None = Query(None, max_length=64),
    severity: str | None = Query(None, max_length=16),
    occurred_from: str | None = Query(None, max_length=40),
    occurred_to: str | None = Query(None, max_length=40),
    include_incidents: bool = Query(True),
    include_policies: bool = Query(True),
    limit: int = Query(10, ge=1, le=50),
    session: AsyncSession = Depends(get_db),
) -> KnowledgeSearchResponse:
    """Return ranked, citable records without executing retrieved text.

    Each result carries a stable evidence ID and an explicit
    ``untrusted_evidence`` trust-boundary marker. Prompt-like text is retained
    as evidence but flagged so downstream agents cannot mistake it for control
    instructions.
    """
    service = KnowledgeRetrievalService(session)
    return await service.search(
        q,
        facility_id=facility_id,
        location_id=location_id,
        event_type=event_type,
        severity=severity,
        occurred_from=occurred_from,
        occurred_to=occurred_to,
        include_incidents=include_incidents,
        include_policies=include_policies,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# 7. Integration Health
# ---------------------------------------------------------------------------


@router.get(
    "/integration-health",
    operation_id="get_integration_health",
    response_model=IntegrationHealthResponse,
    summary="Adapter health status for all evidence sources",
    dependencies=_HUMAN_TOOL_DEPENDENCIES,
)
async def get_integration_health(
    session: AsyncSession = Depends(get_db),
) -> IntegrationHealthResponse:
    # Probe the four adapters
    adapters = [
        MockAccessControlAdapter(session),
        MockScheduleAdapter(session),
        MockWorkOrderAdapter(session),
        MockDeliveryAdapter(session),
    ]
    probe_map: dict[str, dict] = {}
    for adapter in adapters:
        h = await adapter.health_check()
        probe_map[h["source_id"]] = h

    # Include any persisted rows for integrations not directly probed
    stmt = select(IntegrationHealth)
    result = await session.execute(stmt)
    for row in result.scalars().all():
        if row.source_id not in probe_map:
            probe_map[row.source_id] = {
                "source_id": row.source_id,
                "name": row.name,
                "status": row.status,
                "last_checked_at": row.last_checked_at,
                "last_successful_at": row.last_successful_at,
                "latency_ms": row.latency_ms,
                "consecutive_failures": row.consecutive_failures,
                "error_message": row.error_message,
                "adapter_class": row.adapter_class,
            }

    records = [IntegrationHealthRecord(**v) for v in probe_map.values()]
    return IntegrationHealthResponse(
        meta=ToolMeta(source="aggregator", record_count=len(records)),
        records=records,
    )


# ---------------------------------------------------------------------------
# Event-bound Orchestrate façades
# ---------------------------------------------------------------------------


async def _agent_event(event_id: str, session: AsyncSession) -> SecurityEvent:
    """Resolve the immutable server-side scope for every agent tool call."""
    event = await session.get(SecurityEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found.")
    return event


def _agent_meta(
    event_id: str,
    source: str,
    count: int,
    *,
    limit: int = _AGENT_MAX_RECORDS,
) -> AgentToolMeta:
    return AgentToolMeta(
        event_id=event_id,
        source=source,
        record_count=count,
        truncated=count == limit,
    )


@router.get(
    "/agent/event",
    operation_id="get_agent_event_detail",
    response_model=AgentEventDetailResponse,
    summary="Read the compact event detail bound to an event ID",
    dependencies=[Depends(require_permission(_PERM))],
)
async def get_agent_event_detail(
    event_id: str = Query(..., min_length=1, max_length=36),
    session: AsyncSession = Depends(get_db),
) -> AgentEventDetailResponse:
    event = await _agent_event(event_id, session)
    return AgentEventDetailResponse(
        event_id=event.id,
        event_type=event.event_type,
        event_timestamp=event.event_timestamp,
        location_id=event.location_id,
        facility_id=event.facility_id,
        zone=event.zone,
        detector_confidence=event.detector_confidence,
        status=event.status,
    )


@router.get(
    "/agent/camera-metadata",
    operation_id="get_agent_camera_metadata",
    response_model=AgentCameraMetadataResponse,
    summary="Read compact camera metadata bound to an event ID",
    dependencies=[Depends(require_permission(_PERM))],
)
async def get_agent_camera_metadata(
    event_id: str = Query(..., min_length=1, max_length=36),
    session: AsyncSession = Depends(get_db),
) -> AgentCameraMetadataResponse:
    """Return only camera facts already bound to the requested event.

    Camera identifiers are operational device references rather than subject
    identity. Raw camera metadata, URLs, and free-form descriptions are never
    exposed to the agent connection.
    """
    event = await _agent_event(event_id, session)
    return AgentCameraMetadataResponse(
        event_id=event.id,
        camera_id=event.camera_id,
        metadata_status="available" if event.camera_id else "unavailable",
        location_id=event.location_id,
        facility_id=event.facility_id,
        zone=event.zone,
    )


@router.get(
    "/agent/access-events",
    operation_id="get_agent_access_events",
    response_model=AgentAccessResponse,
    summary="Read redacted access facts for the supplied event",
    dependencies=[Depends(require_permission(_PERM))],
)
async def get_agent_access_events(
    event_id: str = Query(..., min_length=1, max_length=36),
    session: AsyncSession = Depends(get_db),
) -> AgentAccessResponse:
    event = await _agent_event(event_id, session)
    adapter = MockAccessControlAdapter(session)
    raw = await adapter.get_access_events(
        event.location_id,
        facility_id=event.facility_id,
        limit=_AGENT_MAX_RECORDS,
    )
    records = [
        AgentAccessFact(
            access_type=row["access_type"],
            access_granted=row["access_granted"],
            occurred_at=row["occurred_at"],
        )
        for row in raw
    ]
    return AgentAccessResponse(
        meta=_agent_meta(event.id, adapter.source_id, len(records)),
        records=records,
    )


@router.get(
    "/agent/schedule",
    operation_id="get_agent_schedule",
    response_model=AgentScheduleResponse,
    summary="Read redacted schedule facts for the supplied event",
    dependencies=[Depends(require_permission(_PERM))],
)
async def get_agent_schedule(
    event_id: str = Query(..., min_length=1, max_length=36),
    session: AsyncSession = Depends(get_db),
) -> AgentScheduleResponse:
    event = await _agent_event(event_id, session)
    adapter = MockScheduleAdapter(session)
    raw = await adapter.get_schedule(
        event.location_id,
        facility_id=event.facility_id,
        limit=_AGENT_MAX_RECORDS,
    )
    records = [
        AgentScheduleFact(
            schedule_type=row["schedule_type"],
            start_time=row["start_time"],
            end_time=row["end_time"],
            is_active=row["is_active"],
        )
        for row in raw
    ]
    return AgentScheduleResponse(
        meta=_agent_meta(event.id, adapter.source_id, len(records)),
        records=records,
    )


@router.get(
    "/agent/work-orders",
    operation_id="get_agent_work_orders",
    response_model=AgentWorkOrdersResponse,
    summary="Read redacted work-order facts for the supplied event",
    dependencies=[Depends(require_permission(_PERM))],
)
async def get_agent_work_orders(
    event_id: str = Query(..., min_length=1, max_length=36),
    session: AsyncSession = Depends(get_db),
) -> AgentWorkOrdersResponse:
    event = await _agent_event(event_id, session)
    adapter = MockWorkOrderAdapter(session)
    raw = await adapter.get_work_orders(
        event.location_id,
        facility_id=event.facility_id,
        limit=_AGENT_MAX_RECORDS,
    )
    records = [
        AgentWorkOrderFact(
            scheduled_start=row["scheduled_start"],
            scheduled_end=row["scheduled_end"],
            status=row["status"],
            requires_after_hours=row["requires_after_hours"],
            approved=bool(row.get("approved_by")),
        )
        for row in raw
    ]
    return AgentWorkOrdersResponse(
        meta=_agent_meta(event.id, adapter.source_id, len(records)),
        records=records,
    )


@router.get(
    "/agent/delivery",
    operation_id="get_agent_delivery",
    response_model=AgentDeliveryResponse,
    summary="Read redacted delivery facts for the supplied event",
    dependencies=[Depends(require_permission(_PERM))],
)
async def get_agent_delivery(
    event_id: str = Query(..., min_length=1, max_length=36),
    session: AsyncSession = Depends(get_db),
) -> AgentDeliveryResponse:
    event = await _agent_event(event_id, session)
    adapter = MockDeliveryAdapter(session)
    raw = await adapter.get_deliveries(
        event.location_id,
        facility_id=event.facility_id,
        limit=_AGENT_MAX_RECORDS,
    )
    records = [
        AgentDeliveryFact(
            scheduled_start=row["scheduled_start"],
            scheduled_end=row["scheduled_end"],
            is_scheduled=row["is_scheduled"],
        )
        for row in raw
    ]
    return AgentDeliveryResponse(
        meta=_agent_meta(event.id, adapter.source_id, len(records)),
        records=records,
    )


@router.get(
    "/agent/location-policy",
    operation_id="get_agent_location_policy",
    response_model=AgentPolicyResponse,
    summary="Read redacted policy facts for the supplied event",
    dependencies=[Depends(require_permission(_PERM))],
)
async def get_agent_location_policy(
    event_id: str = Query(..., min_length=1, max_length=36),
    session: AsyncSession = Depends(get_db),
) -> AgentPolicyResponse:
    event = await _agent_event(event_id, session)
    stmt = (
        select(SecurityRule)
        .where(SecurityRule.is_active.is_(True))
        .where(
            (SecurityRule.location_id == event.location_id) | (SecurityRule.location_id.is_(None))
        )
        .where(
            (SecurityRule.facility_id == event.facility_id) | (SecurityRule.facility_id.is_(None))
        )
        .limit(_AGENT_MAX_RECORDS)
    )
    rows = (await session.execute(stmt)).scalars().all()
    records = [
        AgentPolicyFact(
            rule_type=row.rule_type,
            restricted_after=row.restricted_after,
            restricted_before=row.restricted_before,
            applies_to_zones=row.applies_to_zones,
            is_active=row.is_active,
        )
        for row in rows
    ]
    return AgentPolicyResponse(
        meta=_agent_meta(event.id, "db_security_rules", len(records)),
        records=records,
    )


@router.get(
    "/agent/incident-history",
    operation_id="get_agent_incident_history",
    response_model=AgentIncidentResponse,
    summary="Read redacted incident-history facts for the supplied event",
    dependencies=[Depends(require_permission(_PERM))],
)
async def get_agent_incident_history(
    event_id: str = Query(..., min_length=1, max_length=36),
    session: AsyncSession = Depends(get_db),
) -> AgentIncidentResponse:
    event = await _agent_event(event_id, session)
    stmt = (
        select(IncidentHistory)
        .where(IncidentHistory.location_id == event.location_id)
        .where(IncidentHistory.facility_id == event.facility_id)
        .order_by(IncidentHistory.occurred_at.desc())
        .limit(_AGENT_MAX_RECORDS)
    )
    rows = (await session.execute(stmt)).scalars().all()
    records = [
        AgentIncidentFact(
            incident_type=row.incident_type,
            severity=row.severity,
            occurred_at=row.occurred_at,
            resolved=row.resolved,
        )
        for row in rows
    ]
    return AgentIncidentResponse(
        meta=_agent_meta(event.id, "db_incident_history", len(records)),
        records=records,
    )


@router.get(
    "/agent/integration-health",
    operation_id="get_agent_integration_health",
    response_model=AgentIntegrationResponse,
    summary="Read redacted evidence-source health for the supplied event",
    dependencies=[Depends(require_permission(_PERM))],
)
async def get_agent_integration_health(
    event_id: str = Query(..., min_length=1, max_length=36),
    session: AsyncSession = Depends(get_db),
) -> AgentIntegrationResponse:
    event = await _agent_event(event_id, session)
    adapters = [
        MockAccessControlAdapter(session),
        MockScheduleAdapter(session),
        MockWorkOrderAdapter(session),
        MockDeliveryAdapter(session),
    ]
    health = [await adapter.health_check() for adapter in adapters]
    persisted = (await session.execute(select(IntegrationHealth))).scalars().all()
    known = {item["source_id"] for item in health}
    health.extend(
        {
            "source_id": row.source_id,
            "status": row.status,
            "last_successful_at": row.last_successful_at,
            "consecutive_failures": row.consecutive_failures,
        }
        for row in persisted
        if row.source_id not in known
    )
    records = [
        AgentIntegrationFact(
            source_id=item["source_id"],
            status=item["status"],
            last_successful_at=item.get("last_successful_at"),
            consecutive_failures=item.get("consecutive_failures", 0),
        )
        for item in health[:_AGENT_MAX_RECORDS]
    ]
    return AgentIntegrationResponse(
        meta=_agent_meta(event.id, "aggregator", len(records)),
        records=records,
    )


@router.get(
    "/agent/assessment",
    operation_id="get_agent_assessment",
    response_model=AgentAssessmentResponse,
    summary="Read the compact persisted assessment bound to an event ID",
    dependencies=[Depends(require_permission(_PERM))],
)
async def get_agent_assessment(
    event_id: str = Query(..., min_length=1, max_length=36),
    session: AsyncSession = Depends(get_db),
) -> AgentAssessmentResponse:
    event = await _agent_event(event_id, session)
    assessment = (
        await session.execute(select(RiskAssessment).where(RiskAssessment.event_id == event.id))
    ).scalar_one_or_none()
    if assessment is None:
        raise HTTPException(status_code=404, detail="Assessment not found.")
    recommendation = (
        await session.execute(select(Recommendation).where(Recommendation.event_id == event.id))
    ).scalar_one_or_none()
    return AgentAssessmentResponse(
        event_id=event.id,
        event_status=event.status,
        risk_score=assessment.risk_score,
        risk_level=assessment.risk_level,
        risk_policy_version=assessment.risk_policy_version,
        confidence_score=assessment.confidence_score,
        confidence_level=assessment.confidence_level,
        summary=recommendation.summary if recommendation is not None else "",
        missing_evidence=(
            _json_string_list(recommendation.missing_evidence_json)
            if recommendation is not None
            else []
        ),
        human_review_required=True,
    )
