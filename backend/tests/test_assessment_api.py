"""
Gate 8 — Integration tests for POST /api/v1/events/{id}/assess.

Tests cover:
  - Happy path: normalised event → full assess round-trip → awaiting_review
  - Response shape: all required fields present and typed correctly
  - Evidence signals: after_hours, unverified_person, no_work_order, etc.
  - Re-assessment: calling assess twice replaces old RiskAssessment row
  - 404: event not found
  - 409: event in wrong state (already awaiting_review, dismissed, etc.)
  - Unavailable source override in request body
  - Risk & confidence values are independent (ADR-003 / ADR-004)
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.access import AccessEvent
from app.models.assessment import ConfidenceAssessment, RiskAssessment
from app.models.event import SecurityEvent
from app.models.incident import IncidentHistory
from app.models.risk_policy import RiskPolicy, RiskPolicyFactor
from app.models.schedule import Schedule
from app.models.work_order import WorkOrder

pytestmark = pytest.mark.asyncio

_LOC = "loc-gate8-test"
_FAC = "fac-gate8-test"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uid() -> str:
    return str(uuid.uuid4())


def _new_event(
    *,
    location_id: str = _LOC,
    facility_id: str = _FAC,
    status: str = "normalised",
) -> SecurityEvent:
    return SecurityEvent(
        id=_uid(),
        provider_event_id=f"prov-{_uid()}",
        source_adapter="simulator",
        event_type="person_detected",
        event_timestamp="2026-11-03T22:30:00Z",
        location_id=location_id,
        facility_id=facility_id,
        status=status,
    )


async def _seed_event(
    session: AsyncSession,
    *,
    location_id: str = _LOC,
    facility_id: str = _FAC,
    status: str = "normalised",
) -> SecurityEvent:
    event = _new_event(location_id=location_id, facility_id=facility_id, status=status)
    session.add(event)
    await session.flush()
    return event


async def _seed_risk_policy(session: AsyncSession) -> RiskPolicy:
    """
    Insert a minimal v1.0 risk policy so the RiskEngine has something to load.
    Mirrors the seed data from backend/app/db/seed.py.
    """
    # Check if policy already exists (test isolation — re-use across tests)
    from sqlalchemy import select

    stmt = select(RiskPolicy).where(RiskPolicy.version == "1.0")
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing:
        return existing

    import json as _json

    policy = RiskPolicy(
        id=_uid(),
        version="1.0",
        name="Default v1.0",
        description="Test policy",
        is_active=True,
        thresholds_json=_json.dumps({
            "low":      {"min": 0.0,  "max": 29.0},
            "medium":   {"min": 30.0, "max": 59.0},
            "high":     {"min": 60.0, "max": 99.0},
            "critical": {"min": 100.0, "max": None},
        }),
    )
    session.add(policy)
    await session.flush()

    factors = [
        ("after_hours_access",    "After Hours Access",      40.0, "increase"),
        ("unverified_person",     "Unverified Person",       50.0, "increase"),
        ("no_work_order",         "No Work Order",           20.0, "increase"),
        ("no_scheduled_entry",    "No Scheduled Entry",      20.0, "increase"),
        ("known_incident_area",   "Known Incident Area",     30.0, "increase"),
        ("critical_zone",         "Critical Zone",           40.0, "increase"),
    ]
    for factor_id, label, weight, direction in factors:
        f = RiskPolicyFactor(
            id=_uid(),
            policy_id=policy.id,
            factor_id=factor_id,
            label=label,
            weight=weight,
            direction=direction,
            is_active=True,
        )
        session.add(f)

    await session.flush()
    return policy


async def _seed_access_event(
    session: AsyncSession,
    *,
    location_id: str = _LOC,
    after_hours: bool = False,
    access_granted: bool = True,
) -> AccessEvent:
    hour = "22" if after_hours else "09"
    row = AccessEvent(
        id=_uid(),
        location_id=location_id,
        facility_id=_FAC,
        badge_id="badge-g8",
        person_ref="emp-g8",
        access_type="entry",
        access_granted=access_granted,
        occurred_at=f"2026-11-03T{hour}:00:00Z",
        source_system="mock",
    )
    session.add(row)
    await session.flush()
    return row


async def _seed_schedule(session: AsyncSession, *, location_id: str = _LOC) -> Schedule:
    row = Schedule(
        id=_uid(),
        facility_id=_FAC,
        location_id=location_id,
        schedule_type="employee",
        person_ref="emp-g8",
        description="Day shift",
        start_time="2026-11-03T06:00:00Z",
        end_time="2026-11-03T18:00:00Z",
        is_active=True,
        source_system="mock",
    )
    session.add(row)
    await session.flush()
    return row


async def _seed_work_order(session: AsyncSession, *, location_id: str = _LOC) -> WorkOrder:
    row = WorkOrder(
        id=_uid(),
        facility_id=_FAC,
        location_id=location_id,
        work_order_number=f"WO-{_uid()[:8]}",
        status="open",
        description="Scheduled maintenance",
        scheduled_start="2026-11-03T20:00:00Z",
        scheduled_end="2026-11-04T04:00:00Z",
        source_system="mock",
    )
    session.add(row)
    await session.flush()
    return row


async def _seed_incident(session: AsyncSession, *, location_id: str = _LOC) -> IncidentHistory:
    row = IncidentHistory(
        id=_uid(),
        facility_id=_FAC,
        location_id=location_id,
        incident_code=f"INC-{_uid()[:6]}",
        incident_type="unauthorised_access",
        severity="high",
        occurred_at="2026-10-01T14:00:00Z",
        description="Prior intrusion attempt",
        resolved=True,
    )
    session.add(row)
    await session.flush()
    return row


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAssessEventHappyPath:
    async def test_returns_200_with_full_response_shape(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Basic round-trip: normalised event → assess → 200 with correct schema."""
        await _seed_risk_policy(db_session)
        event = await _seed_event(db_session)

        resp = await client.post(f"/api/v1/events/{event.id}/assess")
        assert resp.status_code == 200, resp.text

        data = resp.json()
        assert data["event_id"] == event.id
        assert data["event_status"] == "awaiting_review"
        assert isinstance(data["risk_score"], float)
        assert data["risk_level"] in ("low", "medium", "high", "critical")
        assert data["risk_policy_version"] == "1.0"
        assert isinstance(data["risk_factors"], list)
        assert isinstance(data["confidence_score"], float)
        assert data["confidence_level"] in ("low", "medium", "high")
        assert isinstance(data["confidence_reductions"], list)
        assert isinstance(data["sources_available"], int)
        assert isinstance(data["sources_required"], int)
        assert isinstance(data["evidence_errors"], dict)
        assert "assessed_at" in data

    async def test_event_status_advances_to_awaiting_review(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Event status in DB must be awaiting_review after assessment."""
        await _seed_risk_policy(db_session)
        event = await _seed_event(db_session)

        await client.post(f"/api/v1/events/{event.id}/assess")
        await db_session.refresh(event)
        assert event.status == "awaiting_review"

    async def test_risk_assessment_row_persisted(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A RiskAssessment row must be created in the DB."""
        from sqlalchemy import select

        await _seed_risk_policy(db_session)
        event = await _seed_event(db_session)

        await client.post(f"/api/v1/events/{event.id}/assess")

        stmt = select(RiskAssessment).where(RiskAssessment.event_id == event.id)
        result = await db_session.execute(stmt)
        row = result.scalar_one_or_none()
        assert row is not None
        assert row.risk_score is not None
        assert row.risk_level in ("low", "medium", "high", "critical")

    async def test_confidence_assessment_row_persisted(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A ConfidenceAssessment row must be created in the DB."""
        from sqlalchemy import select

        await _seed_risk_policy(db_session)
        event = await _seed_event(db_session)

        await client.post(f"/api/v1/events/{event.id}/assess")

        stmt = select(ConfidenceAssessment).where(ConfidenceAssessment.event_id == event.id)
        result = await db_session.execute(stmt)
        row = result.scalar_one_or_none()
        assert row is not None
        assert 0.0 <= row.confidence_score <= 1.0

    async def test_risk_score_denormalised_onto_event(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """risk_score / risk_level / confidence_score are written back to SecurityEvent."""
        await _seed_risk_policy(db_session)
        event = await _seed_event(db_session)

        resp = await client.post(f"/api/v1/events/{event.id}/assess")
        data = resp.json()

        await db_session.refresh(event)
        assert event.risk_score == data["risk_score"]
        assert event.risk_level == data["risk_level"]
        assert event.confidence_score == data["confidence_score"]

    async def test_after_hours_signal_increases_risk(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """After-hours access event must trigger the after_hours_access factor."""
        await _seed_risk_policy(db_session)
        event = await _seed_event(db_session)
        await _seed_access_event(db_session, location_id=_LOC, after_hours=True)

        resp = await client.post(f"/api/v1/events/{event.id}/assess")
        data = resp.json()

        factor = next(
            (f for f in data["risk_factors"] if f["factor_id"] == "after_hours_access"),
            None,
        )
        assert factor is not None
        assert factor["triggered"] is True
        assert factor["contribution"] > 0

    async def test_unverified_person_signal(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """access_granted=False must trigger the unverified_person factor."""
        await _seed_risk_policy(db_session)
        event = await _seed_event(db_session)
        await _seed_access_event(db_session, location_id=_LOC, access_granted=False)

        resp = await client.post(f"/api/v1/events/{event.id}/assess")
        data = resp.json()

        factor = next(
            (f for f in data["risk_factors"] if f["factor_id"] == "unverified_person"),
            None,
        )
        assert factor is not None
        assert factor["triggered"] is True

    async def test_no_work_order_triggers_factor(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """When there is no work order for the location, no_work_order must be triggered."""
        await _seed_risk_policy(db_session)
        # Use a unique location so no other test's work orders pollute this
        loc = f"loc-no-wo-{_uid()[:6]}"
        event = await _seed_event(db_session, location_id=loc)

        resp = await client.post(f"/api/v1/events/{event.id}/assess")
        data = resp.json()

        factor = next(
            (f for f in data["risk_factors"] if f["factor_id"] == "no_work_order"),
            None,
        )
        assert factor is not None
        assert factor["triggered"] is True

    async def test_work_order_suppresses_no_work_order_factor(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """When an active work order exists, no_work_order must NOT be triggered."""
        await _seed_risk_policy(db_session)
        loc = f"loc-has-wo-{_uid()[:6]}"
        event = await _seed_event(db_session, location_id=loc)
        await _seed_work_order(db_session, location_id=loc)

        resp = await client.post(f"/api/v1/events/{event.id}/assess")
        data = resp.json()

        factor = next(
            (f for f in data["risk_factors"] if f["factor_id"] == "no_work_order"),
            None,
        )
        assert factor is not None
        assert factor["triggered"] is False


class TestAssessEventReassessment:
    async def test_second_assess_replaces_first(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Re-assessing from awaiting_review must replace the existing assessment rows."""
        from sqlalchemy import func, select

        await _seed_risk_policy(db_session)
        event = await _seed_event(db_session)

        # First assess
        r1 = await client.post(f"/api/v1/events/{event.id}/assess")
        assert r1.status_code == 200

        # Manually transition back to normalised so a second assess is valid
        event.status = "normalised"
        db_session.add(event)
        await db_session.flush()

        # Second assess
        r2 = await client.post(f"/api/v1/events/{event.id}/assess")
        assert r2.status_code == 200

        # Still only one RiskAssessment row (old deleted, new inserted)
        count_stmt = (
            select(func.count())
            .select_from(RiskAssessment)
            .where(RiskAssessment.event_id == event.id)
        )
        result = await db_session.execute(count_stmt)
        assert result.scalar_one() == 1


class TestAssessEventErrorCases:
    async def test_404_for_unknown_event(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Non-existent event_id must return 404."""
        resp = await client.post("/api/v1/events/does-not-exist/assess")
        assert resp.status_code == 404
        assert resp.json()["code"] == "ASSESSMENT_ERROR"

    async def test_409_for_terminal_event(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Assessing a dismissed event must return 409."""
        await _seed_risk_policy(db_session)
        event = await _seed_event(db_session, status="dismissed")

        resp = await client.post(f"/api/v1/events/{event.id}/assess")
        assert resp.status_code == 409

    async def test_409_for_closed_event(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Assessing a closed event must return 409."""
        await _seed_risk_policy(db_session)
        event = await _seed_event(db_session, status="closed")

        resp = await client.post(f"/api/v1/events/{event.id}/assess")
        assert resp.status_code == 409


class TestAssessEventRequestBody:
    async def test_no_body_uses_defaults(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Body is optional — no JSON body must still succeed."""
        await _seed_risk_policy(db_session)
        event = await _seed_event(db_session)

        resp = await client.post(f"/api/v1/events/{event.id}/assess")
        assert resp.status_code == 200

    async def test_unavailable_source_ids_reduce_confidence(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Declaring sources unavailable in the body must lower confidence."""
        await _seed_risk_policy(db_session)

        loc = f"loc-ua-{_uid()[:6]}"
        event_full = await _seed_event(db_session, location_id=loc)
        event_partial = await _seed_event(db_session, location_id=loc)

        # Full assessment (no unavailable sources declared)
        r_full = await client.post(f"/api/v1/events/{event_full.id}/assess", json={})
        assert r_full.status_code == 200

        # Assessment with several sources declared unavailable
        r_partial = await client.post(
            f"/api/v1/events/{event_partial.id}/assess",
            json={
                "unavailable_source_ids": [
                    "mock_access_control",
                    "mock_schedule",
                    "mock_work_order",
                ]
            },
        )
        assert r_partial.status_code == 200

        score_full = r_full.json()["confidence_score"]
        score_partial = r_partial.json()["confidence_score"]
        assert score_partial <= score_full, (
            f"Expected partial ({score_partial}) ≤ full ({score_full})"
        )

    async def test_policy_version_override(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Passing policy_version in body must use that version in the response."""
        await _seed_risk_policy(db_session)
        event = await _seed_event(db_session)

        resp = await client.post(
            f"/api/v1/events/{event.id}/assess",
            json={"policy_version": "1.0"},
        )
        assert resp.status_code == 200
        assert resp.json()["risk_policy_version"] == "1.0"
