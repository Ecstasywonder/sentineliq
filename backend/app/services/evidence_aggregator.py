"""
EvidenceAggregator — Gate 7.

Orchestrates all four mock adapters plus direct DB queries for location-policy
and incident-history to return a complete AggregatedEvidence bundle for a
given event.  Any adapter failure is caught, logged, and recorded in the
``errors`` dict rather than propagating (partial evidence is still better
than none — the ConfidenceEngine will reduce the score for missing sources).
"""

from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.access_control import MockAccessControlAdapter
from app.integrations.delivery import MockDeliveryAdapter
from app.integrations.schedule import MockScheduleAdapter
from app.integrations.work_order import MockWorkOrderAdapter
from app.models.event import SecurityEvent
from app.models.incident import IncidentHistory
from app.models.integration import IntegrationHealth
from app.models.security_rule import SecurityRule
from app.schemas.knowledge import KnowledgeSearchResponse
from app.schemas.tools import (
    AccessEventRecord,
    AccessEventsResponse,
    AggregatedEvidence,
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
from app.services.knowledge_retrieval import KnowledgeRetrievalService

logger = structlog.get_logger(__name__)

_DEFAULT_LIMIT = 50


class EvidenceAggregator:
    """
    Collects all context evidence for a security event.

    Parameters
    ----------
    session:
        Active async DB session (injected by FastAPI dependency).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._access = MockAccessControlAdapter(session)
        self._schedule = MockScheduleAdapter(session)
        self._work_order = MockWorkOrderAdapter(session)
        self._delivery = MockDeliveryAdapter(session)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def gather(
        self,
        event_id: str,
        location_id: str,
        *,
        facility_id: str | None = None,
        limit: int = _DEFAULT_LIMIT,
    ) -> AggregatedEvidence:
        """
        Gather all evidence for *event_id* at *location_id*.

        Returns a fully-populated (or partially-populated) AggregatedEvidence.
        Never raises — errors are captured in ``AggregatedEvidence.errors``.
        """
        errors: dict[str, str] = {}

        # ---- access events ---------------------------------------------------
        access_resp = await self._safe(
            "access_events",
            self._fetch_access_events(location_id, facility_id=facility_id, limit=limit),
            errors,
        )

        # ---- schedule --------------------------------------------------------
        schedule_resp = await self._safe(
            "schedule",
            self._fetch_schedule(location_id, facility_id=facility_id, limit=limit),
            errors,
        )

        # ---- work orders -----------------------------------------------------
        work_orders_resp = await self._safe(
            "work_orders",
            self._fetch_work_orders(location_id, facility_id=facility_id, limit=limit),
            errors,
        )

        # ---- delivery --------------------------------------------------------
        delivery_resp = await self._safe(
            "delivery",
            self._fetch_deliveries(location_id, facility_id=facility_id, limit=limit),
            errors,
        )

        # ---- location policy -------------------------------------------------
        policy_resp = await self._safe(
            "location_policy",
            self._fetch_location_policy(location_id, facility_id=facility_id),
            errors,
        )

        # ---- incident history ------------------------------------------------
        incident_resp = await self._safe(
            "incident_history",
            self._fetch_incident_history(location_id, facility_id=facility_id, limit=limit),
            errors,
        )

        # ---- semantic / hybrid incident + policy knowledge ------------------
        knowledge_resp = await self._safe(
            "knowledge_search",
            self._fetch_knowledge(
                event_id,
                location_id,
                facility_id=facility_id,
                limit=min(limit, 10),
            ),
            errors,
        )

        # ---- integration health ---------------------------------------------
        health_resp = await self._safe(
            "integration_health",
            self._fetch_integration_health(),
            errors,
        )

        return AggregatedEvidence(
            event_id=event_id,
            access_events=access_resp,
            schedule=schedule_resp,
            work_orders=work_orders_resp,
            delivery=delivery_resp,
            location_policy=policy_resp,
            incident_history=incident_resp,
            knowledge_search=knowledge_resp,
            integration_health=health_resp,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Individual fetch helpers
    # ------------------------------------------------------------------

    async def _fetch_access_events(
        self,
        location_id: str,
        *,
        facility_id: str | None,
        limit: int,
    ) -> AccessEventsResponse:
        raw = await self._access.get_access_events(
            location_id, facility_id=facility_id, limit=limit
        )
        records = [AccessEventRecord(**r) for r in raw]
        return AccessEventsResponse(
            meta=ToolMeta(
                source=self._access.source_id,
                record_count=len(records),
                truncated=len(records) == limit,
            ),
            records=records,
        )

    async def _fetch_schedule(
        self,
        location_id: str,
        *,
        facility_id: str | None,
        limit: int,
    ) -> ScheduleResponse:
        raw = await self._schedule.get_schedule(location_id, facility_id=facility_id, limit=limit)
        records = [ScheduleRecord(**r) for r in raw]
        return ScheduleResponse(
            meta=ToolMeta(
                source=self._schedule.source_id,
                record_count=len(records),
                truncated=len(records) == limit,
            ),
            records=records,
        )

    async def _fetch_work_orders(
        self,
        location_id: str,
        *,
        facility_id: str | None,
        limit: int,
    ) -> WorkOrdersResponse:
        raw = await self._work_order.get_work_orders(
            location_id, facility_id=facility_id, limit=limit
        )
        records = [WorkOrderRecord(**r) for r in raw]
        return WorkOrdersResponse(
            meta=ToolMeta(
                source=self._work_order.source_id,
                record_count=len(records),
                truncated=len(records) == limit,
            ),
            records=records,
        )

    async def _fetch_deliveries(
        self,
        location_id: str,
        *,
        facility_id: str | None,
        limit: int,
    ) -> DeliveryResponse:
        raw = await self._delivery.get_deliveries(location_id, facility_id=facility_id, limit=limit)
        records = [DeliveryRecord(**r) for r in raw]
        return DeliveryResponse(
            meta=ToolMeta(
                source=self._delivery.source_id,
                record_count=len(records),
                truncated=len(records) == limit,
            ),
            records=records,
        )

    async def _fetch_location_policy(
        self,
        location_id: str,
        *,
        facility_id: str | None,
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
        result = await self._session.execute(stmt)
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
            meta=ToolMeta(
                source="db_security_rules",
                record_count=len(records),
            ),
            records=records,
        )

    async def _fetch_incident_history(
        self,
        location_id: str,
        *,
        facility_id: str | None,
        limit: int,
    ) -> IncidentHistoryResponse:
        stmt = (
            select(IncidentHistory)
            .where(IncidentHistory.location_id == location_id)
            .order_by(IncidentHistory.occurred_at.desc())
            .limit(limit)
        )
        if facility_id:
            stmt = stmt.where(IncidentHistory.facility_id == facility_id)
        result = await self._session.execute(stmt)
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

    async def _fetch_integration_health(self) -> IntegrationHealthResponse:
        """
        Merge live adapter health probes with any persisted IntegrationHealth rows.
        Adapter probes win if a source_id matches.
        """
        # Collect adapter health concurrently (sequential is fine for mock)
        adapters = [self._access, self._schedule, self._work_order, self._delivery]
        probe_map: dict[str, dict] = {}
        for adapter in adapters:
            h = await adapter.health_check()
            probe_map[h["source_id"]] = h

        # Fetch persisted rows for any source_ids not probed
        stmt = select(IntegrationHealth)
        result = await self._session.execute(stmt)
        db_rows = result.scalars().all()
        for row in db_rows:
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
            meta=ToolMeta(
                source="aggregator",
                record_count=len(records),
            ),
            records=records,
        )

    async def _fetch_knowledge(
        self,
        event_id: str,
        location_id: str,
        *,
        facility_id: str | None,
        limit: int,
    ) -> KnowledgeSearchResponse:
        event = await self._session.get(SecurityEvent, event_id)
        query_parts = ["security event", location_id]
        if event is not None:
            query_parts.extend(
                value
                for value in (event.event_type, event.zone)
                if isinstance(value, str) and value
            )
        service = KnowledgeRetrievalService(self._session)
        return await service.search(
            " ".join(query_parts),
            facility_id=facility_id,
            location_id=location_id,
            include_incidents=True,
            include_policies=True,
            limit=limit,
        )

    # ------------------------------------------------------------------
    # Error isolation helper
    # ------------------------------------------------------------------

    @staticmethod
    async def _safe(key: str, coro, errors: dict) -> object | None:
        """Await *coro*; on any exception store in *errors* and return None."""
        try:
            return await coro
        except Exception as exc:
            logger.warning("evidence_fetch_failed", source=key, error=str(exc))
            errors[key] = str(exc)
            return None
