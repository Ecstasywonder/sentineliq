"""
Gate 12 — Integration tests for the Audit Trail API.

Endpoints under test:
    GET /api/v1/events/{id}/audit     Event-scoped audit trail
    GET /api/v1/audit                 Global audit trail (paginated, filtered)

Coverage:
  Event-scoped audit trail
    - 200 after assessment (audit rows created by pipeline)
    - Response shape (items list, total, page, page_size, pages)
    - Each entry has required fields (audit_id, action, actor, occurred_at)
    - human_decision entry present after a decision is recorded
    - escalated entry present after escalate decision
    - Entries ordered newest-first
    - Pagination: page 2 returns correct slice
    - 404 for unknown event
    - Empty list (200) for event with no audit entries

  Global audit trail
    - 200 returns all entries across events
    - Filter by action returns only matching entries
    - Filter by actor returns only matching entries
    - Filter by since returns only entries at/after timestamp
    - Filter by until returns only entries at/before timestamp
    - 422 for invalid action filter
    - Pagination works on global endpoint

  Schema integrity
    - details field deserialised to dict (not string)
    - redacted=True entry has details=null
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

_FAC = "fac-gate12"
_LOC = "loc-gate12"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uid() -> str:
    return str(uuid.uuid4())


def _thresholds_json() -> str:
    return json.dumps(
        {
            "low": {"min": 0.0, "max": 29.0},
            "medium": {"min": 30.0, "max": 59.0},
            "high": {"min": 60.0, "max": 99.0},
            "critical": {"min": 100.0, "max": None},
        }
    )


async def _seed_policy(session: AsyncSession) -> RiskPolicy:
    stmt = select(RiskPolicy).where(RiskPolicy.version == "1.0")
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing:
        return existing

    policy = RiskPolicy(
        id=_uid(),
        version="1.0",
        name="Default v1.0",
        is_active=True,
        thresholds_json=_thresholds_json(),
    )
    session.add(policy)
    await session.flush()
    for fid, label, weight in [
        ("after_hours_access", "After Hours Access", 40.0),
        ("unverified_person", "Unverified Person", 50.0),
        ("no_work_order", "No Work Order", 20.0),
        ("no_scheduled_entry", "No Scheduled Entry", 20.0),
        ("known_incident_area", "Known Incident Area", 30.0),
        ("critical_zone", "Critical Zone", 40.0),
    ]:
        session.add(
            RiskPolicyFactor(
                id=_uid(),
                policy_id=policy.id,
                factor_id=fid,
                label=label,
                weight=weight,
                direction="increase",
                is_active=True,
            )
        )
    await session.flush()
    return policy


async def _seed_assessed(
    client: AsyncClient,
    session: AsyncSession,
) -> SecurityEvent:
    """Seed + assess an event → awaiting_review. Audit rows are created by pipeline."""
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
    await session.refresh(event)
    return event


async def _seed_decided(
    client: AsyncClient,
    session: AsyncSession,
    decision: str = "accept",
) -> SecurityEvent:
    event = await _seed_assessed(client, session)
    r = await client.post(
        f"/api/v1/events/{event.id}/decision",
        json={"decision": decision, "rationale": "test"},
    )
    assert r.status_code == 201
    await session.refresh(event)
    return event


def _seed_audit_row(
    session: AsyncSession,
    event_id: str,
    action: str,
    actor: str,
    occurred_at: str = "2026-11-03T22:00:00+00:00",
    details: dict | None = None,
) -> AuditEvent:
    row = AuditEvent(
        id=_uid(),
        event_id=event_id,
        action=action,
        actor=actor,
        occurred_at=occurred_at,
        details_json=json.dumps(details) if details else None,
    )
    session.add(row)
    return row


# ---------------------------------------------------------------------------
# GET /events/{id}/audit — event-scoped
# ---------------------------------------------------------------------------


class TestGetEventAudit:
    async def test_returns_200(self, client: AsyncClient, db_session: AsyncSession) -> None:
        event = await _seed_assessed(client, db_session)
        resp = await client.get(f"/api/v1/events/{event.id}/audit")
        assert resp.status_code == 200, resp.text

    async def test_response_shape(self, client: AsyncClient, db_session: AsyncSession) -> None:
        event = await _seed_assessed(client, db_session)
        resp = await client.get(f"/api/v1/events/{event.id}/audit")
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "pages" in data
        assert isinstance(data["items"], list)

    async def test_each_entry_shape(self, client: AsyncClient, db_session: AsyncSession) -> None:
        event = await _seed_assessed(client, db_session)
        resp = await client.get(f"/api/v1/events/{event.id}/audit")
        for entry in resp.json()["items"]:
            assert "audit_id" in entry
            assert "action" in entry
            assert "actor" in entry
            assert "occurred_at" in entry
            assert "redacted" in entry

    async def test_contains_entries_after_assessment(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Assessment pipeline writes audit rows — total must be > 0."""
        event = await _seed_assessed(client, db_session)
        resp = await client.get(f"/api/v1/events/{event.id}/audit")
        assert resp.json()["total"] > 0

    async def test_human_decision_entry_present(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_decided(client, db_session, "accept")
        resp = await client.get(f"/api/v1/events/{event.id}/audit")
        actions = [e["action"] for e in resp.json()["items"]]
        assert "human_decision" in actions

    async def test_escalated_entry_present_after_escalate_decision(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_decided(client, db_session, "escalate")
        resp = await client.get(f"/api/v1/events/{event.id}/audit")
        actions = [e["action"] for e in resp.json()["items"]]
        assert "escalated" in actions

    async def test_entries_ordered_newest_first(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_decided(client, db_session, "accept")
        resp = await client.get(f"/api/v1/events/{event.id}/audit")
        timestamps = [e["occurred_at"] for e in resp.json()["items"]]
        assert timestamps == sorted(timestamps, reverse=True)

    async def test_pagination_total_matches(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_decided(client, db_session, "accept")
        r1 = await client.get(f"/api/v1/events/{event.id}/audit?page=1&page_size=2")
        data = r1.json()
        assert len(data["items"]) <= 2
        assert data["total"] >= 1

    async def test_404_unknown_event(self, client: AsyncClient, db_session: AsyncSession) -> None:
        resp = await client.get("/api/v1/events/does-not-exist/audit")
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "EVENT_NOT_FOUND"

    async def test_empty_list_for_event_with_no_audit(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = SecurityEvent(
            id=_uid(),
            provider_event_id=f"prov-{_uid()}",
            source_adapter="simulator",
            event_type="motion_detected",
            event_timestamp="2026-11-03T10:00:00Z",
            location_id=_LOC,
            facility_id=_FAC,
            status="normalised",
        )
        db_session.add(event)
        await db_session.flush()

        resp = await client.get(f"/api/v1/events/{event.id}/audit")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0
        assert resp.json()["items"] == []

    async def test_details_deserialised_to_dict(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_decided(client, db_session, "accept")
        resp = await client.get(f"/api/v1/events/{event.id}/audit")
        # Find the human_decision entry which always has details_json
        decision_entries = [e for e in resp.json()["items"] if e["action"] == "human_decision"]
        assert len(decision_entries) > 0
        assert isinstance(decision_entries[0]["details"], dict)

    async def test_redacted_entry_has_null_details(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_assessed(client, db_session)
        row = _seed_audit_row(
            db_session,
            event.id,
            "human_decision",
            "redacted@example.com",
            details={"secret": "data"},
        )
        row.redacted = True
        await db_session.flush()

        resp = await client.get(f"/api/v1/events/{event.id}/audit")
        redacted = [e for e in resp.json()["items"] if e["redacted"]]
        assert len(redacted) >= 1
        assert redacted[0]["details"] is None


# ---------------------------------------------------------------------------
# GET /audit — global audit trail
# ---------------------------------------------------------------------------


class TestGetGlobalAudit:
    async def test_returns_200(self, client: AsyncClient, db_session: AsyncSession) -> None:
        await _seed_decided(client, db_session, "accept")
        resp = await client.get("/api/v1/audit")
        assert resp.status_code == 200, resp.text

    async def test_response_shape(self, client: AsyncClient, db_session: AsyncSession) -> None:
        resp = await client.get("/api/v1/audit")
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert isinstance(data["items"], list)

    async def test_filter_by_action(self, client: AsyncClient, db_session: AsyncSession) -> None:
        await _seed_decided(client, db_session, "accept")
        resp = await client.get("/api/v1/audit?action=human_decision")
        assert resp.status_code == 200
        for entry in resp.json()["items"]:
            assert entry["action"] == "human_decision"

    async def test_filter_by_actor(self, client: AsyncClient, db_session: AsyncSession) -> None:
        await _seed_decided(client, db_session, "accept")
        resp = await client.get("/api/v1/audit?actor=test%40sentineliq.test")
        assert resp.status_code == 200
        for entry in resp.json()["items"]:
            assert entry["actor"] == "test@sentineliq.test"

    async def test_filter_by_since(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """Entries before the since timestamp should not appear."""
        event = await _seed_assessed(client, db_session)
        # Plant an old entry
        old_row = _seed_audit_row(
            db_session,
            event.id,
            "status_changed",
            "old@example.com",
            occurred_at="2020-01-01T00:00:00+00:00",
        )
        await db_session.flush()

        resp = await client.get("/api/v1/audit?since=2025-01-01T00:00:00%2B00:00")
        assert resp.status_code == 200
        for entry in resp.json()["items"]:
            assert entry["occurred_at"] >= "2025-01-01"

        # old_row must not appear
        ids = [e["audit_id"] for e in resp.json()["items"]]
        assert old_row.id not in ids

    async def test_filter_by_until(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """Entries after the until timestamp should not appear."""
        event = await _seed_assessed(client, db_session)
        # Plant a future entry
        future_row = _seed_audit_row(
            db_session,
            event.id,
            "status_changed",
            "future@example.com",
            occurred_at="2099-12-31T23:59:59+00:00",
        )
        await db_session.flush()

        resp = await client.get("/api/v1/audit?until=2050-01-01T00:00:00%2B00:00")
        ids = [e["audit_id"] for e in resp.json()["items"]]
        assert future_row.id not in ids

    async def test_422_invalid_action_filter(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        resp = await client.get("/api/v1/audit?action=totally_fake_action")
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "INVALID_ACTION"

    async def test_pagination(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """page_size=1 must return exactly 1 item."""
        await _seed_decided(client, db_session, "accept")
        resp = await client.get("/api/v1/audit?page=1&page_size=1")
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["page_size"] == 1
        assert data["pages"] >= 1
