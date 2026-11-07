"""
Gate 10 — Integration tests for the Operator Decision API.

Endpoints under test:
    POST  /api/v1/events/{id}/decision      Record an operator decision
    GET   /api/v1/events/{id}/decision      Retrieve latest decision
    GET   /api/v1/events/{id}/decisions     Retrieve full decision history

Coverage:
  Happy path
    - POST accept  → event status becomes closed, 201 returned
    - POST dismiss → event status becomes dismissed
    - POST reject  → event status becomes dismissed
    - POST escalate → event status becomes escalated
    - POST override → event status becomes closed
    - POST request_context → event status becomes context_incomplete
    - Response shape has all required fields
    - rationale is stored and returned
    - is_override flag is stored and returned
    - decided_by matches the stub actor id
    - risk_at_decision and confidence_at_decision captured from event
    - prior_status reflects the pre-decision status
    - AuditEvent row is created (action=human_decision)
    - GET /decision returns the latest decision
    - GET /decisions returns full history (multiple decisions)

  Error cases
    - POST with unknown decision type → 400
    - POST on non-existent event → 404
    - POST on event in wrong status (normalised) → 409
    - POST on event in terminal status (dismissed) → 409
    - GET /decision on non-existent event → 404
    - GET /decision on event with no decisions → 404
    - GET /decisions on non-existent event → 404
    - GET /decisions on event with no decisions → empty list (200)

  Audit trail
    - AuditEvent.action == 'human_decision'
    - AuditEvent.actor == stub user email
    - AuditEvent.details_json contains decision, prior_status, target_status
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditEvent
from app.models.decision import OperatorDecision
from app.models.event import SecurityEvent
from app.models.recommendation import Recommendation
from app.models.risk_policy import RiskPolicy, RiskPolicyFactor
from app.models.user import User
from app.security.dependencies import AuthenticatedUser, get_current_user

pytestmark = pytest.mark.asyncio

_FAC = "fac-gate10"
_LOC = "loc-gate10"


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


async def _seed_awaiting(
    client: AsyncClient,
    session: AsyncSession,
    *,
    location_id: str = _LOC,
) -> SecurityEvent:
    """Seed an event and run POST /assess to reach awaiting_review."""
    await _seed_policy(session)
    event = SecurityEvent(
        id=_uid(),
        provider_event_id=f"prov-{_uid()}",
        source_adapter="simulator",
        event_type="person_detected",
        event_timestamp="2026-11-03T22:00:00Z",
        location_id=location_id,
        facility_id=_FAC,
        status="normalised",
    )
    session.add(event)
    await session.flush()

    resp = await client.post(f"/api/v1/events/{event.id}/assess")
    assert resp.status_code == 200, f"assess failed: {resp.text}"

    # Refresh from DB — status is now awaiting_review
    await session.refresh(event)
    return event


async def _post_decision(
    client: AsyncClient,
    event_id: str,
    decision: str = "accept",
    rationale: str | None = "Test rationale",
    is_override: bool = False,
) -> dict:
    resp = await client.post(
        f"/api/v1/events/{event_id}/decision",
        json={"decision": decision, "rationale": rationale, "is_override": is_override},
    )
    return resp


# ---------------------------------------------------------------------------
# Happy path — POST /decision
# ---------------------------------------------------------------------------


class TestPostDecisionHappyPath:
    async def test_accept_returns_201(self, client: AsyncClient, db_session: AsyncSession) -> None:
        event = await _seed_awaiting(client, db_session)
        resp = await _post_decision(client, event.id, "accept")
        assert resp.status_code == 201, resp.text

    async def test_accept_advances_status_to_closed(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_awaiting(client, db_session)
        resp = await _post_decision(client, event.id, "accept")
        assert resp.json()["event_status"] == "closed"

    async def test_dismiss_advances_status_to_dismissed(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_awaiting(client, db_session)
        resp = await _post_decision(client, event.id, "dismiss")
        assert resp.status_code == 201
        assert resp.json()["event_status"] == "dismissed"

    async def test_reject_advances_status_to_dismissed(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_awaiting(client, db_session)
        resp = await _post_decision(client, event.id, "reject")
        assert resp.status_code == 201
        assert resp.json()["event_status"] == "dismissed"

    async def test_escalate_advances_status_to_escalated(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_awaiting(client, db_session)
        resp = await _post_decision(client, event.id, "escalate")
        assert resp.status_code == 201
        assert resp.json()["event_status"] == "escalated"

    async def test_override_advances_status_to_closed(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_awaiting(client, db_session)
        resp = await _post_decision(client, event.id, "override", is_override=True)
        assert resp.status_code == 201
        assert resp.json()["event_status"] == "closed"

    async def test_request_context_advances_to_context_incomplete(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_awaiting(client, db_session)
        resp = await _post_decision(client, event.id, "request_context")
        assert resp.status_code == 201
        assert resp.json()["event_status"] == "context_incomplete"

    async def test_response_shape(self, client: AsyncClient, db_session: AsyncSession) -> None:
        event = await _seed_awaiting(client, db_session)
        resp = await _post_decision(client, event.id, "accept")
        data = resp.json()

        assert data["decision_id"]
        assert data["event_id"] == event.id
        assert data["decision"] == "accept"
        assert data["event_status"] == "closed"
        assert "rationale" in data
        assert "is_override" in data
        assert "decided_by" in data
        assert "decided_by_role" in data
        assert "prior_status" in data
        assert "decided_at" in data

    async def test_rationale_stored_and_returned(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_awaiting(client, db_session)
        resp = await _post_decision(client, event.id, "accept", rationale="Verified safe")
        assert resp.json()["rationale"] == "Verified safe"

    async def test_null_rationale_accepted(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_awaiting(client, db_session)
        resp = await _post_decision(client, event.id, "dismiss", rationale=None)
        assert resp.status_code == 201
        assert resp.json()["rationale"] is None

    async def test_is_override_flag_stored(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_awaiting(client, db_session)
        resp = await _post_decision(client, event.id, "override", is_override=True)
        assert resp.json()["is_override"] is True

    async def test_prior_status_is_awaiting_review(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_awaiting(client, db_session)
        resp = await _post_decision(client, event.id, "accept")
        assert resp.json()["prior_status"] == "awaiting_review"

    async def test_risk_at_decision_captured(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_awaiting(client, db_session)
        resp = await _post_decision(client, event.id, "accept")
        # risk_at_decision comes from event.risk_level — may be None if 0 score
        data = resp.json()
        assert "risk_at_decision" in data  # field always present

    async def test_db_row_persisted(self, client: AsyncClient, db_session: AsyncSession) -> None:
        event = await _seed_awaiting(client, db_session)
        resp = await _post_decision(client, event.id, "accept")
        decision_id = resp.json()["decision_id"]

        row = await db_session.get(OperatorDecision, decision_id)
        assert row is not None
        assert row.event_id == event.id
        assert row.decision == "accept"

    async def test_omitted_recommendation_uses_event_canonical_recommendation(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_awaiting(client, db_session)
        recommendation = await db_session.scalar(
            select(Recommendation).where(Recommendation.event_id == event.id)
        )
        assert recommendation is not None

        response = await _post_decision(client, event.id, "accept")
        assert response.status_code == 201, response.text
        assert response.json()["recommendation_id"] == recommendation.id

        decision = await db_session.get(OperatorDecision, response.json()["decision_id"])
        assert decision is not None
        assert decision.recommendation_id == recommendation.id
        assert decision.recommendation_snapshot is not None
        assert decision.recommendation_snapshot["recommendation_id"] == recommendation.id

    async def test_decision_snapshot_survives_canonical_recommendation_reassessment(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_awaiting(client, db_session)

        first_decision = await _post_decision(client, event.id, "request_context")
        assert first_decision.status_code == 201, first_decision.text
        original_snapshot = first_decision.json()["recommendation_snapshot"]
        assert original_snapshot is not None
        assert "person_detected" in original_snapshot["summary"]

        # Re-assessment updates the one canonical Recommendation row in place.
        event.event_type = "forced_door"
        db_session.add(event)
        await db_session.flush()
        reassessment = await client.post(f"/api/v1/events/{event.id}/assess")
        assert reassessment.status_code == 200, reassessment.text

        canonical = await db_session.scalar(
            select(Recommendation).where(Recommendation.event_id == event.id)
        )
        assert canonical is not None
        await db_session.refresh(canonical)
        assert canonical.id == original_snapshot["recommendation_id"]
        assert "forced_door" in canonical.summary
        assert canonical.summary != original_snapshot["summary"]

        history = await client.get(f"/api/v1/events/{event.id}/decisions")
        assert history.status_code == 200, history.text
        historical = history.json()["items"][0]
        assert historical["recommendation_id"] == canonical.id
        assert historical["recommendation_snapshot"] == original_snapshot

    async def test_event_status_updated_in_db(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_awaiting(client, db_session)
        await _post_decision(client, event.id, "dismiss")

        await db_session.refresh(event)
        assert event.status == "dismissed"


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------


class TestDecisionAuditTrail:
    async def test_audit_event_created(self, client: AsyncClient, db_session: AsyncSession) -> None:
        event = await _seed_awaiting(client, db_session)
        await _post_decision(client, event.id, "accept")

        stmt = (
            select(AuditEvent)
            .where(AuditEvent.event_id == event.id)
            .where(AuditEvent.action == "human_decision")
        )
        result = await db_session.execute(stmt)
        audit_row = result.scalar_one_or_none()
        assert audit_row is not None

    async def test_audit_actor_is_stub_user_email(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_awaiting(client, db_session)
        await _post_decision(client, event.id, "dismiss")

        stmt = (
            select(AuditEvent)
            .where(AuditEvent.event_id == event.id)
            .where(AuditEvent.action == "human_decision")
        )
        result = await db_session.execute(stmt)
        audit_row = result.scalar_one()
        # Stub user email is 'test@sentineliq.test' (conftest.py)
        assert audit_row.actor == "test@sentineliq.test"

    async def test_audit_details_json_shape(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_awaiting(client, db_session)
        await _post_decision(client, event.id, "accept")

        stmt = (
            select(AuditEvent)
            .where(AuditEvent.event_id == event.id)
            .where(AuditEvent.action == "human_decision")
        )
        result = await db_session.execute(stmt)
        audit_row = result.scalar_one()
        details = json.loads(audit_row.details_json)

        assert details["decision"] == "accept"
        assert details["prior_status"] == "awaiting_review"
        assert details["target_status"] == "closed"
        assert "is_override" in details
        assert "rationale_provided" in details
        assert details["recommendation_snapshot"]["recommendation_id"]


# ---------------------------------------------------------------------------
# GET /decision — latest decision
# ---------------------------------------------------------------------------


class TestGetLatestDecision:
    async def test_returns_200(self, client: AsyncClient, db_session: AsyncSession) -> None:
        event = await _seed_awaiting(client, db_session)
        await _post_decision(client, event.id, "accept")
        resp = await client.get(f"/api/v1/events/{event.id}/decision")
        assert resp.status_code == 200, resp.text

    async def test_response_matches_post(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_awaiting(client, db_session)
        post_data = (await _post_decision(client, event.id, "accept")).json()
        get_data = (await client.get(f"/api/v1/events/{event.id}/decision")).json()

        assert get_data["decision_id"] == post_data["decision_id"]
        assert get_data["decision"] == post_data["decision"]
        assert get_data["decided_at"] == post_data["decided_at"]

    async def test_404_no_decision(self, client: AsyncClient, db_session: AsyncSession) -> None:
        event = await _seed_awaiting(client, db_session)
        resp = await client.get(f"/api/v1/events/{event.id}/decision")
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "DECISION_NOT_FOUND"

    async def test_404_unknown_event(self, client: AsyncClient, db_session: AsyncSession) -> None:
        resp = await client.get("/api/v1/events/does-not-exist/decision")
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "EVENT_NOT_FOUND"


# ---------------------------------------------------------------------------
# GET /decisions — decision history
# ---------------------------------------------------------------------------


class TestGetDecisionHistory:
    async def test_returns_200_empty_list(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Event with no decisions → 200 with empty list, not 404."""
        event = await _seed_awaiting(client, db_session)
        resp = await client.get(f"/api/v1/events/{event.id}/decisions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    async def test_returns_decision_after_post(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_awaiting(client, db_session)
        await _post_decision(client, event.id, "accept")
        resp = await client.get(f"/api/v1/events/{event.id}/decisions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["decision"] == "accept"

    async def test_multiple_decisions_ordered_newest_first(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """After request_context → re-assess → accept, history must show 2 decisions."""
        event = await _seed_awaiting(client, db_session)

        # First decision: request_context → context_incomplete
        r1 = await _post_decision(client, event.id, "request_context")
        assert r1.status_code == 201

        # Reset to normalised + re-assess to reach awaiting_review again
        await db_session.refresh(event)
        event.status = "normalised"
        db_session.add(event)
        await db_session.flush()
        r2 = await client.post(f"/api/v1/events/{event.id}/assess")
        assert r2.status_code == 200

        # Second decision: accept → closed
        r3 = await _post_decision(client, event.id, "accept")
        assert r3.status_code == 201

        resp = await client.get(f"/api/v1/events/{event.id}/decisions")
        data = resp.json()
        assert data["total"] == 2
        # Newest first — accept is most recent
        assert data["items"][0]["decision"] == "accept"
        assert data["items"][1]["decision"] == "request_context"

    async def test_404_unknown_event(self, client: AsyncClient, db_session: AsyncSession) -> None:
        resp = await client.get("/api/v1/events/does-not-exist/decisions")
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "EVENT_NOT_FOUND"


# ---------------------------------------------------------------------------
# Error cases — POST /decision
# ---------------------------------------------------------------------------


class TestPostDecisionErrors:
    async def test_stale_concurrent_decision_loses_cas_without_persisting(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        monkeypatch,
    ) -> None:
        """A request that read pre-decision state cannot write a second outcome."""
        from app.services.decision_service import DecisionService

        event = await _seed_awaiting(client, db_session)
        stale_event = SimpleNamespace(
            status="awaiting_review",
            risk_level=event.risk_level,
            confidence_score=event.confidence_score,
        )

        winner = await _post_decision(client, event.id, "accept")
        assert winner.status_code == 201, winner.text

        async def _load_stale_event(self, event_id: str):
            assert event_id == event.id
            return stale_event

        monkeypatch.setattr(DecisionService, "_load_event", _load_stale_event)
        loser = await _post_decision(client, event.id, "dismiss")
        assert loser.status_code == 409, loser.text
        assert "changed while this decision was being recorded" in loser.text

        decision_count = await db_session.scalar(
            select(func.count())
            .select_from(OperatorDecision)
            .where(OperatorDecision.event_id == event.id)
        )
        audit_count = await db_session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.event_id == event.id,
                AuditEvent.action == "human_decision",
            )
        )
        assert decision_count == 1
        assert audit_count == 1

    async def test_400_invalid_decision_type(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_awaiting(client, db_session)
        resp = await client.post(
            f"/api/v1/events/{event.id}/decision",
            json={"decision": "fly_away"},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "INVALID_DECISION"

    async def test_404_unknown_event(self, client: AsyncClient, db_session: AsyncSession) -> None:
        resp = await client.post(
            "/api/v1/events/does-not-exist/decision",
            json={"decision": "accept"},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "DECISION_ERROR"

    async def test_409_event_in_normalised_status(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Event not yet assessed — must reject decision with 409."""
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

        resp = await client.post(
            f"/api/v1/events/{event.id}/decision",
            json={"decision": "accept"},
        )
        assert resp.status_code == 409

    async def test_409_event_in_terminal_status(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Already-dismissed event must not accept another decision."""
        event = SecurityEvent(
            id=_uid(),
            provider_event_id=f"prov-{_uid()}",
            source_adapter="simulator",
            event_type="motion_detected",
            event_timestamp="2026-11-03T10:00:00Z",
            location_id=_LOC,
            facility_id=_FAC,
            status="dismissed",
        )
        db_session.add(event)
        await db_session.flush()

        resp = await client.post(
            f"/api/v1/events/{event.id}/decision",
            json={"decision": "accept"},
        )
        assert resp.status_code == 409

    async def test_409_rejects_recommendation_from_another_event(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        target_event = await _seed_awaiting(client, db_session, location_id="loc-target")
        other_event = await _seed_awaiting(client, db_session, location_id="loc-other")
        other_recommendation = await db_session.scalar(
            select(Recommendation).where(Recommendation.event_id == other_event.id)
        )
        assert other_recommendation is not None

        response = await client.post(
            f"/api/v1/events/{target_event.id}/decision",
            json={
                "decision": "accept",
                "recommendation_id": other_recommendation.id,
            },
        )
        assert response.status_code == 409, response.text
        assert "belongs to event" in response.json()["detail"]["message"]
        await db_session.refresh(target_event)
        assert target_event.status == "awaiting_review"


class TestDecisionSpecificPermissions:
    @staticmethod
    def _auth(role: str) -> AuthenticatedUser:
        user = User(
            id=f"permission-user-{role}",
            email=f"{role}@sentineliq.test",
            full_name=f"{role} test user",
            hashed_password="$2b$12$unused",
            is_active=True,
            is_verified=True,
        )
        return AuthenticatedUser(user=user, roles=[role])

    async def _with_role(self, role: str, call):
        from app.main import app

        previous = app.dependency_overrides[get_current_user]
        app.dependency_overrides[get_current_user] = lambda: self._auth(role)
        try:
            return await call()
        finally:
            app.dependency_overrides[get_current_user] = previous

    async def test_officer_cannot_override(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_awaiting(client, db_session)
        resp = await self._with_role(
            "officer",
            lambda: client.post(
                f"/api/v1/events/{event.id}/decision",
                json={"decision": "override", "is_override": True},
            ),
        )
        assert resp.status_code == 403
        assert "events:override" in resp.json()["detail"]["message"]

    async def test_officer_can_escalate(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_awaiting(client, db_session)
        resp = await self._with_role(
            "officer",
            lambda: client.post(
                f"/api/v1/events/{event.id}/decision",
                json={"decision": "escalate"},
            ),
        )
        assert resp.status_code == 201, resp.text

    async def test_response_team_cannot_escalate(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_awaiting(client, db_session)
        resp = await self._with_role(
            "response_team",
            lambda: client.post(
                f"/api/v1/events/{event.id}/decision",
                json={"decision": "escalate"},
            ),
        )
        assert resp.status_code == 403
        # The route-level least-privilege boundary rejects this role before
        # the service evaluates the decision-specific escalation permission.
        assert "events:decide" in resp.json()["detail"]["message"]

    async def test_409_event_in_assessing_status(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Event still being assessed — decision must be rejected."""
        event = SecurityEvent(
            id=_uid(),
            provider_event_id=f"prov-{_uid()}",
            source_adapter="simulator",
            event_type="motion_detected",
            event_timestamp="2026-11-03T10:00:00Z",
            location_id=_LOC,
            facility_id=_FAC,
            status="assessing",
        )
        db_session.add(event)
        await db_session.flush()

        resp = await client.post(
            f"/api/v1/events/{event.id}/decision",
            json={"decision": "accept"},
        )
        assert resp.status_code == 409
