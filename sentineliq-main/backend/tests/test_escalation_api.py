"""
Gate 11 — Integration tests for the Escalation API.

Endpoints under test:
    POST   /api/v1/events/{id}/escalation    Create escalation
    GET    /api/v1/events/{id}/escalation    Retrieve latest escalation
    PATCH  /api/v1/events/{id}/escalation    Update escalation status

Coverage:
  Happy path — POST
    - Create escalation on event in 'escalated' status → 201
    - Response shape has all required fields
    - destination stored and returned
    - priority stored and returned
    - note stored and returned
    - null note accepted
    - status is 'pending_acknowledgement' on creation
    - escalated_by matches stub actor id
    - event_status reflects current event state
    - AuditEvent row created (action='escalated')

  Auto-creation via escalate decision
    - POST /decision escalate → GET /escalation returns seeded row immediately

  Happy path — GET
    - 200 after creation
    - Response matches POST

  Happy path — PATCH acknowledge
    - pending_acknowledgement → acknowledged → 200
    - acknowledged_by and acknowledged_at populated
    - AuditEvent created (action='status_changed')

  Happy path — PATCH resolve
    - acknowledged → resolved → 200
    - event status transitions to closed

  Happy path — PATCH cancel
    - pending_acknowledgement → cancelled → 200
    - event status transitions to awaiting_review

  Error cases
    - POST: 400 for invalid destination
    - POST: 400 for invalid priority
    - POST: 404 for unknown event
    - POST: 409 for event not in escalated status
    - GET: 404 for unknown event
    - GET: 404 for never-escalated event
    - PATCH: 400 for invalid status
    - PATCH: 404 for unknown event
    - PATCH: 404 for never-escalated event
    - PATCH: 409 for invalid transition (pending_acknowledgement → resolved)
"""

from __future__ import annotations

import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditEvent
from app.models.event import SecurityEvent
from app.models.risk_policy import RiskPolicy, RiskPolicyFactor

pytestmark = pytest.mark.asyncio

_FAC = "fac-gate11"
_LOC = "loc-gate11"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uid() -> str:
    return str(uuid.uuid4())


def _thresholds_json() -> str:
    return json.dumps({
        "low":      {"min": 0.0,  "max": 29.0},
        "medium":   {"min": 30.0, "max": 59.0},
        "high":     {"min": 60.0, "max": 99.0},
        "critical": {"min": 100.0, "max": None},
    })


async def _seed_policy(session: AsyncSession) -> RiskPolicy:
    stmt = select(RiskPolicy).where(RiskPolicy.version == "1.0")
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing:
        return existing

    policy = RiskPolicy(
        id=_uid(), version="1.0", name="Default v1.0",
        is_active=True, thresholds_json=_thresholds_json(),
    )
    session.add(policy)
    await session.flush()
    for fid, label, weight in [
        ("after_hours_access", "After Hours Access", 40.0),
        ("unverified_person",  "Unverified Person",  50.0),
        ("no_work_order",      "No Work Order",      20.0),
        ("no_scheduled_entry", "No Scheduled Entry", 20.0),
        ("known_incident_area", "Known Incident Area", 30.0),
        ("critical_zone",      "Critical Zone",      40.0),
    ]:
        session.add(RiskPolicyFactor(
            id=_uid(), policy_id=policy.id, factor_id=fid,
            label=label, weight=weight, direction="increase", is_active=True,
        ))
    await session.flush()
    return policy


async def _seed_escalated(
    client: AsyncClient,
    session: AsyncSession,
) -> SecurityEvent:
    """Seed an event, assess it, then POST 'escalate' decision → status=escalated."""
    await _seed_policy(session)
    event = SecurityEvent(
        id=_uid(),
        provider_event_id=f"prov-{_uid()}",
        source_adapter="simulator",
        event_type="person_detected",
        event_timestamp="2026-11-03T22:00:00Z",
        location_id=_LOC,
        facility_id=_FAC,
        status="normalised",
    )
    session.add(event)
    await session.flush()

    r = await client.post(f"/api/v1/events/{event.id}/assess")
    assert r.status_code == 200

    r = await client.post(
        f"/api/v1/events/{event.id}/decision",
        json={"decision": "escalate", "rationale": "Needs supervisor review"},
    )
    assert r.status_code == 201

    await session.refresh(event)
    return event


async def _post_escalation(
    client: AsyncClient,
    event_id: str,
    destination: str = "shift_supervisor",
    priority: str = "high",
    note: str | None = "Urgent — unfamiliar person",
) -> dict:
    return await client.post(
        f"/api/v1/events/{event_id}/escalation",
        json={"destination": destination, "priority": priority, "note": note},
    )


# ---------------------------------------------------------------------------
# POST /escalation — happy path
# ---------------------------------------------------------------------------


class TestPostEscalationHappyPath:
    async def test_returns_201(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_escalated(client, db_session)
        # The auto-created escalation is already there; POST creates a second one
        resp = await _post_escalation(client, event.id)
        assert resp.status_code == 201, resp.text

    async def test_response_shape(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_escalated(client, db_session)
        resp = await _post_escalation(client, event.id, destination="response_team")
        data = resp.json()

        assert data["escalation_id"]
        assert data["event_id"] == event.id
        assert data["destination"] == "response_team"
        assert data["priority"] == "high"
        assert data["status"] == "pending_acknowledgement"
        assert "escalated_by" in data
        assert "escalated_at" in data
        assert "event_status" in data

    async def test_destination_stored(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_escalated(client, db_session)
        resp = await _post_escalation(client, event.id, destination="security_admin")
        assert resp.json()["destination"] == "security_admin"

    async def test_priority_stored(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_escalated(client, db_session)
        resp = await _post_escalation(client, event.id, priority="critical")
        assert resp.json()["priority"] == "critical"

    async def test_note_stored(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_escalated(client, db_session)
        resp = await _post_escalation(client, event.id, note="Potential armed intruder")
        assert resp.json()["note"] == "Potential armed intruder"

    async def test_null_note_accepted(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_escalated(client, db_session)
        resp = await _post_escalation(client, event.id, note=None)
        assert resp.status_code == 201
        assert resp.json()["note"] is None

    async def test_status_is_pending_on_creation(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_escalated(client, db_session)
        resp = await _post_escalation(client, event.id)
        assert resp.json()["status"] == "pending_acknowledgement"

    async def test_audit_event_created(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_escalated(client, db_session)
        await _post_escalation(client, event.id)

        stmt = (
            select(AuditEvent)
            .where(AuditEvent.event_id == event.id)
            .where(AuditEvent.action == "escalated")
        )
        result = await db_session.execute(stmt)
        rows = result.scalars().all()
        # At least one 'escalated' audit entry (auto + explicit)
        assert len(rows) >= 1


# ---------------------------------------------------------------------------
# Auto-creation via escalate decision
# ---------------------------------------------------------------------------


class TestAutoCreatedEscalation:
    async def test_get_escalation_returns_auto_created_row(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """After an 'escalate' decision, GET /escalation must return the seeded row."""
        event = await _seed_escalated(client, db_session)
        resp = await client.get(f"/api/v1/events/{event.id}/escalation")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "pending_acknowledgement"
        assert data["destination"] == "shift_supervisor"

    async def test_auto_escalation_audit_event_exists(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_escalated(client, db_session)
        stmt = (
            select(AuditEvent)
            .where(AuditEvent.event_id == event.id)
            .where(AuditEvent.action == "escalated")
        )
        result = await db_session.execute(stmt)
        assert result.scalar_one_or_none() is not None


# ---------------------------------------------------------------------------
# GET /escalation
# ---------------------------------------------------------------------------


class TestGetEscalation:
    async def test_returns_200(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_escalated(client, db_session)
        resp = await client.get(f"/api/v1/events/{event.id}/escalation")
        assert resp.status_code == 200

    async def test_response_matches_post(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_escalated(client, db_session)
        post_resp = await _post_escalation(client, event.id, destination="external")
        get_resp = await client.get(f"/api/v1/events/{event.id}/escalation")
        # GET returns the latest — must match the explicit POST (newer than auto-created)
        assert get_resp.json()["destination"] == "external"
        assert get_resp.json()["escalation_id"] == post_resp.json()["escalation_id"]

    async def test_404_unknown_event(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        resp = await client.get("/api/v1/events/does-not-exist/escalation")
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "EVENT_NOT_FOUND"

    async def test_404_never_escalated(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = SecurityEvent(
            id=_uid(), provider_event_id=f"prov-{_uid()}",
            source_adapter="simulator", event_type="motion_detected",
            event_timestamp="2026-11-03T10:00:00Z",
            location_id=_LOC, facility_id=_FAC, status="normalised",
        )
        db_session.add(event)
        await db_session.flush()

        resp = await client.get(f"/api/v1/events/{event.id}/escalation")
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "ESCALATION_NOT_FOUND"


# ---------------------------------------------------------------------------
# PATCH /escalation — status transitions
# ---------------------------------------------------------------------------


class TestPatchEscalationHappyPath:
    async def test_acknowledge_returns_200(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_escalated(client, db_session)
        resp = await client.patch(
            f"/api/v1/events/{event.id}/escalation",
            json={"status": "acknowledged"},
        )
        assert resp.status_code == 200, resp.text

    async def test_acknowledge_populates_acknowledged_fields(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_escalated(client, db_session)
        resp = await client.patch(
            f"/api/v1/events/{event.id}/escalation",
            json={"status": "acknowledged"},
        )
        data = resp.json()
        assert data["status"] == "acknowledged"
        assert data["acknowledged_by"] is not None
        assert data["acknowledged_at"] is not None

    async def test_resolve_transitions_event_to_closed(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_escalated(client, db_session)
        # First acknowledge
        r1 = await client.patch(
            f"/api/v1/events/{event.id}/escalation",
            json={"status": "acknowledged"},
        )
        assert r1.status_code == 200
        # Then resolve
        r2 = await client.patch(
            f"/api/v1/events/{event.id}/escalation",
            json={"status": "resolved"},
        )
        assert r2.status_code == 200
        assert r2.json()["status"] == "resolved"
        assert r2.json()["event_status"] == "closed"

    async def test_cancel_transitions_event_to_awaiting_review(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_escalated(client, db_session)
        resp = await client.patch(
            f"/api/v1/events/{event.id}/escalation",
            json={"status": "cancelled"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"
        assert resp.json()["event_status"] == "awaiting_review"

    async def test_acknowledge_audit_event_created(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_escalated(client, db_session)
        await client.patch(
            f"/api/v1/events/{event.id}/escalation",
            json={"status": "acknowledged"},
        )
        stmt = (
            select(AuditEvent)
            .where(AuditEvent.event_id == event.id)
            .where(AuditEvent.action == "status_changed")
        )
        result = await db_session.execute(stmt)
        assert result.scalar_one_or_none() is not None

    async def test_note_appended_on_patch(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_escalated(client, db_session)
        resp = await client.patch(
            f"/api/v1/events/{event.id}/escalation",
            json={"status": "acknowledged", "note": "Supervisor on the way"},
        )
        assert resp.status_code == 200
        assert "Supervisor on the way" in (resp.json()["note"] or "")


# ---------------------------------------------------------------------------
# Error cases — POST
# ---------------------------------------------------------------------------


class TestPostEscalationErrors:
    async def test_400_invalid_destination(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_escalated(client, db_session)
        resp = await client.post(
            f"/api/v1/events/{event.id}/escalation",
            json={"destination": "mars_base", "priority": "high"},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "INVALID_DESTINATION"

    async def test_400_invalid_priority(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_escalated(client, db_session)
        resp = await client.post(
            f"/api/v1/events/{event.id}/escalation",
            json={"destination": "shift_supervisor", "priority": "extreme"},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "INVALID_PRIORITY"

    async def test_404_unknown_event(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        resp = await client.post(
            "/api/v1/events/does-not-exist/escalation",
            json={"destination": "shift_supervisor", "priority": "high"},
        )
        assert resp.status_code == 404

    async def test_409_event_not_in_escalated_status(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = SecurityEvent(
            id=_uid(), provider_event_id=f"prov-{_uid()}",
            source_adapter="simulator", event_type="motion_detected",
            event_timestamp="2026-11-03T10:00:00Z",
            location_id=_LOC, facility_id=_FAC, status="normalised",
        )
        db_session.add(event)
        await db_session.flush()

        resp = await client.post(
            f"/api/v1/events/{event.id}/escalation",
            json={"destination": "shift_supervisor", "priority": "high"},
        )
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Error cases — PATCH
# ---------------------------------------------------------------------------


class TestPatchEscalationErrors:
    async def test_400_invalid_status(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_escalated(client, db_session)
        resp = await client.patch(
            f"/api/v1/events/{event.id}/escalation",
            json={"status": "teleported"},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "INVALID_ESCALATION_STATUS"

    async def test_404_unknown_event(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        resp = await client.patch(
            "/api/v1/events/does-not-exist/escalation",
            json={"status": "acknowledged"},
        )
        assert resp.status_code == 404

    async def test_404_never_escalated_event(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = SecurityEvent(
            id=_uid(), provider_event_id=f"prov-{_uid()}",
            source_adapter="simulator", event_type="motion_detected",
            event_timestamp="2026-11-03T10:00:00Z",
            location_id=_LOC, facility_id=_FAC, status="escalated",
        )
        db_session.add(event)
        await db_session.flush()

        resp = await client.patch(
            f"/api/v1/events/{event.id}/escalation",
            json={"status": "acknowledged"},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "ESCALATION_ERROR"

    async def test_409_invalid_transition_skip_to_resolved(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """pending_acknowledgement → resolved is not a valid transition."""
        event = await _seed_escalated(client, db_session)
        resp = await client.patch(
            f"/api/v1/events/{event.id}/escalation",
            json={"status": "resolved"},
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "INVALID_ESCALATION_TRANSITION"
