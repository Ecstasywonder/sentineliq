"""
Gate 7 — Unit tests for EvidenceAggregator service.

Tests verify:
  - gather() returns a complete AggregatedEvidence with all 7 sections
  - Empty DB → all sections have record_count == 0
  - Seeded rows surface in the correct sections
  - errors dict is empty when all adapters succeed
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.access import AccessEvent
from app.models.delivery import Delivery
from app.models.incident import IncidentHistory
from app.models.schedule import Schedule
from app.models.security_rule import SecurityRule
from app.models.work_order import WorkOrder
from app.services.evidence_aggregator import EvidenceAggregator

pytestmark = pytest.mark.asyncio

_LOC = "agg-loc-001"
_FAC = "agg-fac-001"


def _uid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Basic structure tests
# ---------------------------------------------------------------------------


class TestEvidenceAggregatorStructure:
    async def test_gather_returns_aggregated_evidence(self, db_session: AsyncSession):
        agg = EvidenceAggregator(db_session)
        result = await agg.gather("event-001", _LOC, facility_id=_FAC)
        assert result.event_id == "event-001"

    async def test_all_sections_present_when_empty(self, db_session: AsyncSession):
        agg = EvidenceAggregator(db_session)
        result = await agg.gather("event-002", "loc-empty", facility_id=None)
        assert result.access_events is not None
        assert result.schedule is not None
        assert result.work_orders is not None
        assert result.delivery is not None
        assert result.location_policy is not None
        assert result.incident_history is not None
        assert result.integration_health is not None

    async def test_empty_db_gives_zero_counts(self, db_session: AsyncSession):
        agg = EvidenceAggregator(db_session)
        result = await agg.gather("event-003", "loc-zero")
        assert result.access_events.meta.record_count == 0  # type: ignore[union-attr]
        assert result.schedule.meta.record_count == 0  # type: ignore[union-attr]
        assert result.work_orders.meta.record_count == 0  # type: ignore[union-attr]
        assert result.delivery.meta.record_count == 0  # type: ignore[union-attr]
        assert result.incident_history.meta.record_count == 0  # type: ignore[union-attr]

    async def test_no_errors_on_healthy_db(self, db_session: AsyncSession):
        agg = EvidenceAggregator(db_session)
        result = await agg.gather("event-004", _LOC)
        assert result.errors == {}

    async def test_integration_health_has_four_adapters(self, db_session: AsyncSession):
        agg = EvidenceAggregator(db_session)
        result = await agg.gather("event-005", _LOC)
        source_ids = {r.source_id for r in result.integration_health.records}  # type: ignore[union-attr]
        assert "mock_access_control" in source_ids
        assert "mock_schedule" in source_ids
        assert "mock_work_order" in source_ids
        assert "mock_delivery" in source_ids


# ---------------------------------------------------------------------------
# Seeded-data tests
# ---------------------------------------------------------------------------


class TestEvidenceAggregatorWithData:
    async def test_access_events_populated(self, db_session: AsyncSession):
        row = AccessEvent(
            id=_uid(),
            location_id=_LOC,
            facility_id=_FAC,
            access_type="entry",
            access_granted=True,
            occurred_at="2026-11-03T08:00:00Z",
            source_system="mock",
        )
        db_session.add(row)
        await db_session.flush()

        agg = EvidenceAggregator(db_session)
        result = await agg.gather("event-a1", _LOC, facility_id=_FAC)
        assert result.access_events.meta.record_count >= 1  # type: ignore[union-attr]
        assert result.access_events.records[0].access_type == "entry"  # type: ignore[union-attr]

    async def test_schedule_populated(self, db_session: AsyncSession):
        row = Schedule(
            id=_uid(),
            facility_id=_FAC,
            location_id=_LOC,
            schedule_type="maintenance",
            start_time="2026-11-03T09:00:00Z",
            end_time="2026-11-03T17:00:00Z",
            is_active=True,
            source_system="mock",
        )
        db_session.add(row)
        await db_session.flush()

        agg = EvidenceAggregator(db_session)
        result = await agg.gather("event-s1", _LOC)
        assert result.schedule.meta.record_count >= 1  # type: ignore[union-attr]

    async def test_work_orders_populated(self, db_session: AsyncSession):
        row = WorkOrder(
            id=_uid(),
            location_id=_LOC,
            work_order_number=f"WO-{_uid()[:8]}",
            scheduled_start="2026-11-03T10:00:00Z",
            scheduled_end="2026-11-03T12:00:00Z",
            status="open",
            requires_after_hours=False,
            source_system="mock",
        )
        db_session.add(row)
        await db_session.flush()

        agg = EvidenceAggregator(db_session)
        result = await agg.gather("event-w1", _LOC)
        assert result.work_orders.meta.record_count >= 1  # type: ignore[union-attr]

    async def test_delivery_populated(self, db_session: AsyncSession):
        row = Delivery(
            id=_uid(),
            location_id=_LOC,
            supplier_name="TestCo",
            scheduled_start="2026-11-03T11:00:00Z",
            scheduled_end="2026-11-03T11:30:00Z",
            is_scheduled=True,
            source_system="mock",
        )
        db_session.add(row)
        await db_session.flush()

        agg = EvidenceAggregator(db_session)
        result = await agg.gather("event-d1", _LOC)
        assert result.delivery.meta.record_count >= 1  # type: ignore[union-attr]

    async def test_location_policy_populated(self, db_session: AsyncSession):
        row = SecurityRule(
            id=_uid(),
            location_id=_LOC,
            rule_code=f"RULE-{_uid()[:8]}",
            rule_type="access_restriction",
            description="Restricted zone",
            is_active=True,
        )
        db_session.add(row)
        await db_session.flush()

        agg = EvidenceAggregator(db_session)
        result = await agg.gather("event-p1", _LOC)
        assert result.location_policy.meta.record_count >= 1  # type: ignore[union-attr]

    async def test_incident_history_populated(self, db_session: AsyncSession):
        row = IncidentHistory(
            id=_uid(),
            location_id=_LOC,
            incident_code=f"INC-{_uid()[:8]}",
            incident_type="intrusion",
            severity="high",
            occurred_at="2026-10-15T22:00:00Z",
            description="Motion detected in restricted zone",
            resolved=False,
        )
        db_session.add(row)
        await db_session.flush()

        agg = EvidenceAggregator(db_session)
        result = await agg.gather("event-i1", _LOC)
        assert result.incident_history.meta.record_count >= 1  # type: ignore[union-attr]
        assert result.incident_history.records[0].incident_type == "intrusion"  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# ToolMeta tests
# ---------------------------------------------------------------------------


class TestToolMeta:
    async def test_truncated_flag_set_at_limit(self, db_session: AsyncSession):
        """When result count == limit, truncated should be True."""
        for _ in range(3):
            row = AccessEvent(
                id=_uid(),
                location_id="loc-trunc",
                access_type="entry",
                access_granted=True,
                occurred_at="2026-11-03T07:00:00Z",
                source_system="mock",
            )
            db_session.add(row)
        await db_session.flush()

        agg = EvidenceAggregator(db_session)
        result = await agg.gather("event-t1", "loc-trunc", limit=3)
        # If exactly 3 rows and limit=3, truncated=True
        assert result.access_events.meta.truncated is True  # type: ignore[union-attr]

    async def test_truncated_false_when_under_limit(self, db_session: AsyncSession):
        row = AccessEvent(
            id=_uid(),
            location_id="loc-under",
            access_type="exit",
            access_granted=True,
            occurred_at="2026-11-03T09:00:00Z",
            source_system="mock",
        )
        db_session.add(row)
        await db_session.flush()

        agg = EvidenceAggregator(db_session)
        result = await agg.gather("event-t2", "loc-under", limit=50)
        assert result.access_events.meta.truncated is False  # type: ignore[union-attr]
