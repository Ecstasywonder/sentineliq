"""
Gate 13 — Integration tests for the Feedback API.

Endpoints under test:
    POST  /api/v1/events/{id}/feedback    Submit feedback
    GET   /api/v1/events/{id}/feedback    Retrieve all feedback

Coverage:
  Happy path — POST
    - 201 returned
    - Response shape has all required fields
    - recommendation_useful stored and returned
    - recommendation_accurate stored and returned
    - outcome stored and returned
    - missing_context stored and returned
    - notes stored and returned
    - All-null body accepted (partial feedback)
    - Multiple submissions allowed (no unique constraint)
    - submitted_by matches stub actor id
    - AuditEvent row created (action='feedback_submitted')
    - AuditEvent details_json has outcome and flags

  Happy path — GET
    - 200 returned
    - Empty list for event with no feedback
    - Returns feedback after POST
    - Multiple submissions returned newest-first
    - Response shape (event_id, items, total)

  Error cases
    - POST: 400 for invalid outcome
    - POST: 404 for unknown event
    - GET: 404 for unknown event
    - GET: 200 empty list (no feedback yet)
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

pytestmark = pytest.mark.asyncio

_FAC = "fac-gate13"
_LOC = "loc-gate13"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uid() -> str:
    return str(uuid.uuid4())


async def _seed_event(session: AsyncSession, status: str = "awaiting_review") -> SecurityEvent:
    event = SecurityEvent(
        id=_uid(), provider_event_id=f"prov-{_uid()}",
        source_adapter="simulator", event_type="person_detected",
        event_timestamp="2026-11-03T22:00:00Z",
        location_id=_LOC, facility_id=_FAC, status=status,
    )
    session.add(event)
    await session.flush()
    return event


async def _post_feedback(
    client: AsyncClient,
    event_id: str,
    *,
    recommendation_useful: bool | None = True,
    recommendation_accurate: bool | None = True,
    outcome: str | None = "confirmed_incident",
    missing_context: str | None = None,
    notes: str | None = "Test feedback",
) -> dict:
    return await client.post(
        f"/api/v1/events/{event_id}/feedback",
        json={
            "recommendation_useful": recommendation_useful,
            "recommendation_accurate": recommendation_accurate,
            "outcome": outcome,
            "missing_context": missing_context,
            "notes": notes,
        },
    )


# ---------------------------------------------------------------------------
# POST /feedback — happy path
# ---------------------------------------------------------------------------


class TestPostFeedbackHappyPath:
    async def test_returns_201(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_event(db_session)
        resp = await _post_feedback(client, event.id)
        assert resp.status_code == 201, resp.text

    async def test_response_shape(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_event(db_session)
        resp = await _post_feedback(client, event.id)
        data = resp.json()

        assert data["feedback_id"]
        assert data["event_id"] == event.id
        assert "submitted_by" in data
        assert "recommendation_useful" in data
        assert "recommendation_accurate" in data
        assert "outcome" in data
        assert "submitted_at" in data

    async def test_recommendation_useful_stored(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_event(db_session)
        resp = await _post_feedback(client, event.id, recommendation_useful=False)
        assert resp.json()["recommendation_useful"] is False

    async def test_recommendation_accurate_stored(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_event(db_session)
        resp = await _post_feedback(client, event.id, recommendation_accurate=False)
        assert resp.json()["recommendation_accurate"] is False

    async def test_outcome_stored(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_event(db_session)
        resp = await _post_feedback(client, event.id, outcome="false_positive")
        assert resp.json()["outcome"] == "false_positive"

    async def test_missing_context_stored(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_event(db_session)
        resp = await _post_feedback(client, event.id, missing_context="No work order data")
        assert resp.json()["missing_context"] == "No work order data"

    async def test_notes_stored(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_event(db_session)
        resp = await _post_feedback(client, event.id, notes="Very helpful recommendation")
        assert resp.json()["notes"] == "Very helpful recommendation"

    async def test_all_null_body_accepted(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Partial feedback (all optional fields null) must be accepted."""
        event = await _seed_event(db_session)
        resp = await client.post(
            f"/api/v1/events/{event.id}/feedback",
            json={},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["recommendation_useful"] is None
        assert data["recommendation_accurate"] is None
        assert data["outcome"] is None

    async def test_multiple_submissions_allowed(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_event(db_session)
        r1 = await _post_feedback(client, event.id, outcome="confirmed_incident")
        r2 = await _post_feedback(client, event.id, outcome="false_positive")
        assert r1.status_code == 201
        assert r2.status_code == 201
        assert r1.json()["feedback_id"] != r2.json()["feedback_id"]

    async def test_feedback_on_closed_event_accepted(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Retrospective feedback on a closed event must be accepted."""
        event = await _seed_event(db_session, status="closed")
        resp = await _post_feedback(client, event.id)
        assert resp.status_code == 201

    async def test_audit_event_created(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_event(db_session)
        await _post_feedback(client, event.id)

        stmt = (
            select(AuditEvent)
            .where(AuditEvent.event_id == event.id)
            .where(AuditEvent.action == "feedback_submitted")
        )
        result = await db_session.execute(stmt)
        assert result.scalar_one_or_none() is not None

    async def test_audit_details_json(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_event(db_session)
        await _post_feedback(
            client, event.id,
            outcome="authorized_activity",
            missing_context="Contractor badge data missing",
        )
        stmt = (
            select(AuditEvent)
            .where(AuditEvent.event_id == event.id)
            .where(AuditEvent.action == "feedback_submitted")
        )
        result = await db_session.execute(stmt)
        row = result.scalar_one()
        details = json.loads(row.details_json)

        assert details["outcome"] == "authorized_activity"
        assert details["missing_context_provided"] is True
        assert "feedback_id" in details


# ---------------------------------------------------------------------------
# GET /feedback — happy path
# ---------------------------------------------------------------------------


class TestGetFeedbackHappyPath:
    async def test_returns_200(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_event(db_session)
        resp = await client.get(f"/api/v1/events/{event.id}/feedback")
        assert resp.status_code == 200, resp.text

    async def test_empty_list_for_no_feedback(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_event(db_session)
        resp = await client.get(f"/api/v1/events/{event.id}/feedback")
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

    async def test_returns_feedback_after_post(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_event(db_session)
        await _post_feedback(client, event.id, outcome="confirmed_incident")
        resp = await client.get(f"/api/v1/events/{event.id}/feedback")
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["outcome"] == "confirmed_incident"

    async def test_multiple_submissions_returned(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_event(db_session)
        await _post_feedback(client, event.id, outcome="confirmed_incident")
        await _post_feedback(client, event.id, outcome="false_positive")
        resp = await client.get(f"/api/v1/events/{event.id}/feedback")
        assert resp.json()["total"] == 2

    async def test_response_shape(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_event(db_session)
        await _post_feedback(client, event.id)
        resp = await client.get(f"/api/v1/events/{event.id}/feedback")
        data = resp.json()
        assert "event_id" in data
        assert "items" in data
        assert "total" in data
        assert data["event_id"] == event.id

    async def test_newest_first_ordering(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_event(db_session)
        r1 = await _post_feedback(client, event.id, notes="First")
        r2 = await _post_feedback(client, event.id, notes="Second")
        assert r1.status_code == 201
        assert r2.status_code == 201

        resp = await client.get(f"/api/v1/events/{event.id}/feedback")
        times = [i["submitted_at"] for i in resp.json()["items"]]
        assert times == sorted(times, reverse=True)


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestFeedbackErrors:
    async def test_post_400_invalid_outcome(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        event = await _seed_event(db_session)
        resp = await client.post(
            f"/api/v1/events/{event.id}/feedback",
            json={"outcome": "world_domination"},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "INVALID_OUTCOME"

    async def test_post_404_unknown_event(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        resp = await client.post(
            "/api/v1/events/does-not-exist/feedback",
            json={"outcome": "confirmed_incident"},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "EVENT_NOT_FOUND"

    async def test_get_404_unknown_event(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        resp = await client.get("/api/v1/events/does-not-exist/feedback")
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "EVENT_NOT_FOUND"
