"""
Gate 9 — Integration tests for GET /api/v1/events/{id}/assessment/factors.

Tests cover:
  - Happy path: assess then retrieve factor breakdown (200)
  - Full response shape (assessment_id, event_id, risk_policy_version,
    risk_score, risk_level, factors list, assessed_at)
  - Each factor has the required sub-fields
  - Factors list matches the factors returned by POST /assess
  - 404 when event does not exist
  - 404 when event has never been assessed
  - Only triggered factors contribute a non-zero score
"""

from __future__ import annotations

import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import SecurityEvent
from app.models.risk_policy import RiskPolicy, RiskPolicyFactor

pytestmark = pytest.mark.asyncio

_LOC = "loc-gate9-factors"
_FAC = "fac-gate9-factors"


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
                factor_id=factor_id,
                label=label,
                weight=weight,
                direction="increase",
                is_active=True,
            )
        )
    await session.flush()
    return policy


async def _seed_and_assess(
    client: AsyncClient,
    session: AsyncSession,
    *,
    location_id: str = _LOC,
    event_timestamp: str = "2026-11-03T22:00:00Z",
) -> SecurityEvent:
    """Seed a normalised event and POST /assess it via API."""
    await _seed_policy(session)
    event = SecurityEvent(
        id=_uid(),
        provider_event_id=f"prov-{_uid()}",
        source_adapter="simulator",
        event_type="person_detected",
        event_timestamp=event_timestamp,
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
# Tests: GET /events/{id}/assessment/factors
# ---------------------------------------------------------------------------


class TestGetAssessmentFactorsHappyPath:
    async def test_returns_200(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """Basic retrieval: assess then GET /factors must return 200."""
        event = await _seed_and_assess(client, db_session)
        resp = await client.get(f"/api/v1/events/{event.id}/assessment/factors")
        assert resp.status_code == 200, resp.text

    async def test_response_shape(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """All required top-level fields must be present with correct types."""
        event = await _seed_and_assess(client, db_session)
        resp = await client.get(f"/api/v1/events/{event.id}/assessment/factors")
        data = resp.json()

        assert data["assessment_id"]
        assert data["event_id"] == event.id
        assert data["risk_policy_version"] == "1.0"
        assert isinstance(data["risk_score"], float)
        assert data["risk_level"] in ("low", "medium", "high", "critical")
        assert isinstance(data["factors"], list)
        assert "assessed_at" in data

    async def test_factors_non_empty(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """factors list must contain at least one item after assessment."""
        event = await _seed_and_assess(client, db_session)
        resp = await client.get(f"/api/v1/events/{event.id}/assessment/factors")
        assert len(resp.json()["factors"]) > 0

    async def test_each_factor_shape(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """Each factor must have all required sub-fields."""
        event = await _seed_and_assess(client, db_session)
        resp = await client.get(f"/api/v1/events/{event.id}/assessment/factors")
        for f in resp.json()["factors"]:
            assert "factor_id" in f
            assert "label" in f
            assert "weight" in f
            assert "direction" in f
            assert "triggered" in f
            assert "contribution" in f

    async def test_factors_match_assess_response(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Factors from GET /factors must match the POST /assess response."""
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
        assess_factors = {f["factor_id"]: f for f in assess_resp.json()["risk_factors"]}

        factors_resp = await client.get(f"/api/v1/events/{event.id}/assessment/factors")
        assert factors_resp.status_code == 200
        get_factors = {f["factor_id"]: f for f in factors_resp.json()["factors"]}

        # Same set of factor IDs
        assert set(assess_factors) == set(get_factors)
        # Weights and contributions match
        for fid in assess_factors:
            assert assess_factors[fid]["weight"] == get_factors[fid]["weight"]
            assert assess_factors[fid]["contribution"] == get_factors[fid]["contribution"]
            assert assess_factors[fid]["triggered"] == get_factors[fid]["triggered"]

    async def test_risk_score_matches_assessment(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """risk_score in factors response must match the full assessment response."""
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
        full_score = assess_resp.json()["risk_score"]

        factors_resp = await client.get(f"/api/v1/events/{event.id}/assessment/factors")
        factors_score = factors_resp.json()["risk_score"]

        assert factors_score == full_score

    async def test_triggered_factor_has_nonzero_contribution(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Any triggered factor must have a contribution > 0."""
        event = await _seed_and_assess(client, db_session)
        resp = await client.get(f"/api/v1/events/{event.id}/assessment/factors")
        for f in resp.json()["factors"]:
            if f["triggered"]:
                assert f["contribution"] > 0, (
                    f"Factor {f['factor_id']} is triggered but has zero contribution"
                )

    async def test_untriggered_factor_has_zero_contribution(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Untriggered factors must have contribution == 0.0."""
        event = await _seed_and_assess(client, db_session)
        resp = await client.get(f"/api/v1/events/{event.id}/assessment/factors")
        for f in resp.json()["factors"]:
            if not f["triggered"]:
                assert f["contribution"] == 0.0, (
                    f"Factor {f['factor_id']} is NOT triggered but has nonzero contribution"
                )


# ---------------------------------------------------------------------------
# Tests: error cases
# ---------------------------------------------------------------------------


class TestGetAssessmentFactorsErrors:
    async def test_404_for_unknown_event(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Non-existent event must return 404 with EVENT_NOT_FOUND code."""
        resp = await client.get("/api/v1/events/does-not-exist/assessment/factors")
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "EVENT_NOT_FOUND"

    async def test_404_for_unassessed_event(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Event that exists but was never assessed must return 404 with ASSESSMENT_NOT_FOUND."""
        event = SecurityEvent(
            id=_uid(),
            provider_event_id=f"prov-{_uid()}",
            source_adapter="simulator",
            event_type="motion_detected",
            event_timestamp="2026-11-03T10:00:00Z",
            location_id="loc-never-factors",
            facility_id=_FAC,
            status="normalised",
        )
        db_session.add(event)
        await db_session.flush()

        resp = await client.get(f"/api/v1/events/{event.id}/assessment/factors")
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "ASSESSMENT_NOT_FOUND"
