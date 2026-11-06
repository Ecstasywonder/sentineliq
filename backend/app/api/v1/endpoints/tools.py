"""
Gate 7 — Context Tool endpoints.

All endpoints are read-only (ADR-005) and require the ``tools:read`` permission.
They mirror the seven tools available to the watsonx Orchestrate agents.

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
from app.models.incident import IncidentHistory
from app.models.integration import IntegrationHealth
from app.models.assessment import RiskAssessment
from app.models.event import SecurityEvent
from app.models.security_rule import SecurityRule
from app.schemas.explanation import AssessmentBundleResponse
from app.schemas.knowledge import KnowledgeSearchResponse
from app.schemas.tools import (
    AccessEventRecord,
    AccessEventsResponse,
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
from app.security.dependencies import require_permission
from app.services.knowledge_retrieval import KnowledgeRetrievalService

router = APIRouter()

_PERM = "tools:read"
_MAX_LIMIT = 200


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


# ---------------------------------------------------------------------------
# 1. Access Events
# ---------------------------------------------------------------------------


@router.get(
    "/assessment-bundle",
    operation_id="get_assessment_bundle",
    response_model=AssessmentBundleResponse,
    summary="Retrieve the persisted assessment reconstruction bundle",
    dependencies=[Depends(require_permission(_PERM))],
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
    dependencies=[Depends(require_permission(_PERM))],
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
    dependencies=[Depends(require_permission(_PERM))],
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
    dependencies=[Depends(require_permission(_PERM))],
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
    dependencies=[Depends(require_permission(_PERM))],
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
    dependencies=[Depends(require_permission(_PERM))],
)
async def get_location_policy(
    location_id: str = Query(..., description="Location identifier"),
    facility_id: str | None = Query(None),
    session: AsyncSession = Depends(get_db),
) -> LocationPolicyResponse:
    stmt = (
        select(SecurityRule)
        .where(SecurityRule.is_active.is_(True))
        .where(
            (SecurityRule.location_id == location_id)
            | (SecurityRule.location_id.is_(None))
        )
    )
    if facility_id:
        stmt = stmt.where(
            (SecurityRule.facility_id == facility_id)
            | (SecurityRule.facility_id.is_(None))
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
    dependencies=[Depends(require_permission(_PERM))],
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
    dependencies=[Depends(require_permission(_PERM))],
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
    dependencies=[Depends(require_permission(_PERM))],
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
