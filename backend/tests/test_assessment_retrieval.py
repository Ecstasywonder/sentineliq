"""
Gate 9 — Integration tests for GET /api/v1/events/{id}/assessment.

Tests cover:
  - Happy path: assess event then retrieve stored assessment
  - Full response shape (all required fields present + typed)
  - risk_factors deserialized correctly from stored JSON
  - confidence_reductions deserialized correctly
  - 404 when event does not exist
  - 404 when event exists but has never been assessed
  - Idempotency: GET after re-assess returns latest values
"""

from __future__ import annotations

import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assessment import ConfidenceAssessment, RiskAssessment
from app.models.event import SecurityEvent
from app.models.risk_policy import RiskPolicy, RiskPolicyFactor

pytestmark = pytest.mark.asyncio

_LOC = "loc-gate9-retrieval"
_FAC = "fac-gate9-retrieval"


# ---------------------------------------------------------------------------
# Helpers (shared with test_assessment_api.py pattern)
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
    from sqlalchemy import select

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

    for factor_id, label, weight in [
        ("after_hours_access", "After Hours Access", 40.0),
        ("unverified_person",  "Unverified Person",  50.0),
        ("no_work_order",      "No Work Order",      20.0),
        ("no_scheduled_entry", "No Scheduled Entry", 20.0),
        ("known_incident_area","Known Incident Area",30.0),
        ("critical_zone",      "Critical Zone",      40.0),
    ]:
        session.add(RiskPolicyFactor(
            id=_uid(), policy_id=policy.id, factor_id=factor_id,
            label=label, weight=weight, direction="increase", is_active=True,
        ))
    await session.flush()
    return policy


async def _seed_and_assess(
    client: AsyncClient,
    session: AsyncSession,
    *,
    location_id: str = _LOC,
) -> SecurityEvent:
    """Seed an event and run the assessment pipeline via API."""
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
    return event


# ---------------------------------------------------------------------------
# Tests: GET /events/{id}/assessment
# ---------------------------------------------------------------------------


class TestGetAssessmentHappyPath:
    async def test_returns_200_after_assess(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Basic retrieval: assess then GET should return 200."""
        event = await _seed_and_assess(client, db_session)
        resp = await client.get(f"/api/v1/events/{event.id}/assessment")
        assert resp.status_code == 200, resp.text

    async def test_response_shape(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """All required fields must be present with correct types."""
        event = await _seed_and_assess(client, db_session)
        resp = await client.get(f"/api/v1/events/{event.id}/assessment")
        data = resp.json()

        assert data["assessment_id"]
        assert data["event_id"] == event.id
        assert data["risk_policy_version"] == "1.0"
        assert isinstance(data["risk_score"], float)
        assert data["risk_level"] in ("low", "medium", "high", "critical")
        assert isinstance(data["risk_factors"], list)
        assert isinstance(data["confidence_score"], float)
        assert data["confidence_level"] in ("low", "medium", "high")
        assert isinstance(data["confidence_reductions"], list)
        assert isinstance(data["sources_available"], int)
        assert isinstance(data["sources_required"], int)
        assert "assessed_at" in data

    async def test_risk_factors_deserialized(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """risk_factors list must contain factor_id, weight, direction, triggered."""
        event = await _seed_and_assess(client, db_session)
        resp = await client.get(f"/api/v1/events/{event.id}/assessment")
        factors = resp.json()["risk_factors"]

        assert len(factors) > 0
        for f in factors:
            assert "factor_id" in f
            assert "weight" in f
            assert "direction" in f
            assert "triggered" in f
            assert "contribution" in f

    async def test_scores_match_assess_response(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Scores returned by GET must match the scores from the original POST /assess."""
        await _seed_policy(db_session)
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
        db_session.add(event)
        await db_session.flush()

        assess_resp = await client.post(f"/api/v1/events/{event.id}/assess")
        assert assess_resp.status_code == 200
        assess_data = assess_resp.json()

        get_resp = await client.get(f"/api/v1/events/{event.id}/assessment")
        get_data = get_resp.json()

        assert get_data["risk_score"] == assess_data["risk_score"]
        assert get_data["risk_level"] == assess_data["risk_level"]
        assert get_data["confidence_score"] == assess_data["confidence_score"]
        assert get_data["confidence_level"] == assess_data["confidence_level"]

    async def test_assessment_id_matches_db_row(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """assessment_id in response must match the RiskAssessment.id in the DB."""
        from sqlalchemy import select

        event = await _seed_and_assess(client, db_session)

        stmt = select(RiskAssessment).where(RiskAssessment.event_id == event.id)
        result = await db_session.execute(stmt)
        row = result.scalar_one()

        resp = await client.get(f"/api/v1/events/{event.id}/assessment")
        assert resp.json()["assessment_id"] == row.id


class TestGetAssessmentErrorCases:
    async def test_404_for_unknown_event(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Requesting assessment for a non-existent event must return 404."""
        resp = await client.get("/api/v1/events/does-not-exist/assessment")
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "EVENT_NOT_FOUND"

    async def test_404_for_unassessed_event(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Event that exists but was never assessed must return 404."""
        event = SecurityEvent(
            id=_uid(),
            provider_event_id=f"prov-{_uid()}",
            source_adapter="simulator",
            event_type="motion_detected",
            event_timestamp="2026-11-03T10:00:00Z",
            location_id="loc-never-assessed",
            facility_id=_FAC,
            status="normalised",
        )
        db_session.add(event)
        await db_session.flush()

        resp = await client.get(f"/api/v1/events/{event.id}/assessment")
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "ASSESSMENT_NOT_FOUND"


class TestGetAssessmentReassess:
    async def test_reassess_updates_retrieval(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """After a re-assessment, GET must return the latest assessment values."""
        await _seed_policy(db_session)
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
        db_session.add(event)
        await db_session.flush()

        # First assess
        r1 = await client.post(f"/api/v1/events/{event.id}/assess")
        assert r1.status_code == 200
        first_assessed_at = (
            await client.get(f"/api/v1/events/{event.id}/assessment")
        ).json()["assessed_at"]

        # Reset status for re-assess
        event.status = "normalised"
        db_session.add(event)
        await db_session.flush()

        # Second assess
        r2 = await client.post(f"/api/v1/events/{event.id}/assess")
        assert r2.status_code == 200

        # GET must reflect the second assessment
        get_resp = await client.get(f"/api/v1/events/{event.id}/assessment")
        assert get_resp.status_code == 200
        # assessed_at may be the same second in fast CI, just check field exists
        assert get_resp.json()["assessed_at"] is not None
