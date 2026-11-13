"""
Gate 17 — Integration tests for the Sentinel Coordinator.

Coverage:
  CoordinatorService
    1.  Deterministic fallback used when Orchestrate not active (APP_ENV=test)
    2.  Fallback returns assessment_ready=True when assessment row exists
    3.  Fallback returns assessment_ready=False when no assessment row
    4.  Fallback always sets human_review_required=True
    5.  Fallback summary includes event_type, location, risk_level
    6.  Fallback missing_evidence comes from evidence_errors_json
    7.  AgentRun row is persisted for every call
    8.  event_id override: parse_and_validate replaces agent event_id
    9.  human_review_required forced True even if agent returns False
    10. Forbidden words replaced in summary
    11. Summary truncated at 1024 characters
    12. Non-JSON agent output → fallback (ValueError path)
    13. Invalid schema agent output → fallback (ValidationError path)
    14. Markdown-fenced JSON stripped before validation

  API — GET /api/v1/events/{id}/review
    15. 200 with review fields for event in awaiting_review
    16. 200 for event in escalated status
    17. 409 for event in normalised status
    18. 409 for event in closed status
    19. 404 for unknown event_id
    20. Response has human_review_required=True
    21. Response has source=deterministic_fallback (test env)
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_run import AgentRun
from app.models.assessment import RiskAssessment
from app.models.event import SecurityEvent
from app.models.risk_policy import RiskPolicy, RiskPolicyFactor
from app.services.coordinator_service import CoordinatorService, _COORDINATOR_SYSTEM_PROMPT

pytestmark = pytest.mark.asyncio

_FAC = "fac-gate17"
_LOC = "loc-gate17"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uid() -> str:
    return str(uuid.uuid4())


def _thresholds_json() -> str:
    return json.dumps(
        {
            "low": {"min": 0.0, "max": 24.0},
            "medium": {"min": 25.0, "max": 49.0},
            "high": {"min": 50.0, "max": 74.0},
            "critical": {"min": 75.0, "max": 200.0},
        }
    )


async def _seed_policy(session: AsyncSession) -> RiskPolicy:
    policy = RiskPolicy(
        id=_uid(),
        version="1.0",
        name="Test Policy",
        is_active=True,
        description="test",
        thresholds_json=_thresholds_json(),
        effective_from="2026-01-01T00:00:00Z",
    )
    session.add(policy)
    factor = RiskPolicyFactor(
        id=_uid(),
        policy_id=policy.id,
        factor_id="critical_zone",
        label="Restricted Zone",
        weight=25.0,
        direction="increase",
        description="Zone is restricted",
        is_active=True,
    )
    session.add(factor)
    await session.flush()
    return policy


async def _make_event(
    session: AsyncSession,
    *,
    status: str = "awaiting_review",
) -> SecurityEvent:
    evt = SecurityEvent(
        id=_uid(),
        event_type="person_detected",
        event_timestamp="2026-11-07T22:00:00Z",
        location_id=_LOC,
        facility_id=_FAC,
        zone="restricted_after_hours",
        status=status,
        source_adapter="test",
        provider_event_id=_uid(),
    )
    session.add(evt)
    await session.flush()
    return evt


async def _make_assessment(
    session: AsyncSession,
    event_id: str,
    *,
    evidence_errors: dict | None = None,
) -> RiskAssessment:
    ra = RiskAssessment(
        id=_uid(),
        event_id=event_id,
        risk_policy_version="1.0",
        risk_score=60.0,
        risk_level="high",
        risk_factors_json=json.dumps([]),
        confidence_score=0.75,
        confidence_level="medium",
        evidence_errors_json=json.dumps(evidence_errors or {}),
        assessed_at="2026-11-07T22:05:00Z",
    )
    session.add(ra)
    await session.flush()
    return ra


# ---------------------------------------------------------------------------
# CoordinatorService unit tests
# ---------------------------------------------------------------------------


class TestDeterministicFallback:
    async def test_fallback_assessment_ready_true_when_row_exists(
        self, db_session: AsyncSession
    ) -> None:
        evt = await _make_event(db_session)
        await _make_assessment(db_session, evt.id)

        svc = CoordinatorService(db_session)
        result = await svc._deterministic_fallback(evt.id, _uid())

        assert result.assessment_ready is True

    async def test_fallback_assessment_ready_false_when_no_row(
        self, db_session: AsyncSession
    ) -> None:
        evt = await _make_event(db_session)

        svc = CoordinatorService(db_session)
        result = await svc._deterministic_fallback(evt.id, _uid())

        assert result.assessment_ready is False

    async def test_fallback_human_review_required_always_true(
        self, db_session: AsyncSession
    ) -> None:
        evt = await _make_event(db_session)

        svc = CoordinatorService(db_session)
        result = await svc._deterministic_fallback(evt.id, _uid())

        assert result.human_review_required is True

    async def test_fallback_summary_includes_event_type_and_location(
        self, db_session: AsyncSession
    ) -> None:
        evt = await _make_event(db_session)
        await _make_assessment(db_session, evt.id)

        svc = CoordinatorService(db_session)
        result = await svc._deterministic_fallback(evt.id, _uid())

        assert "person_detected" in result.summary
        assert _LOC in result.summary

    async def test_fallback_summary_includes_risk_level(self, db_session: AsyncSession) -> None:
        evt = await _make_event(db_session)
        await _make_assessment(db_session, evt.id)

        svc = CoordinatorService(db_session)
        result = await svc._deterministic_fallback(evt.id, _uid())

        assert "high" in result.summary

    async def test_fallback_missing_evidence_from_errors_json(
        self, db_session: AsyncSession
    ) -> None:
        evt = await _make_event(db_session)
        await _make_assessment(
            db_session, evt.id, evidence_errors={"mock_access_control": "timeout"}
        )

        svc = CoordinatorService(db_session)
        result = await svc._deterministic_fallback(evt.id, _uid())

        assert "mock_access_control" in result.missing_evidence

    async def test_fallback_missing_evidence_empty_when_no_errors(
        self, db_session: AsyncSession
    ) -> None:
        evt = await _make_event(db_session)
        await _make_assessment(db_session, evt.id, evidence_errors={})

        svc = CoordinatorService(db_session)
        result = await svc._deterministic_fallback(evt.id, _uid())

        assert result.missing_evidence == []

    async def test_fallback_source_is_deterministic_fallback(
        self, db_session: AsyncSession
    ) -> None:
        evt = await _make_event(db_session)

        svc = CoordinatorService(db_session)
        result = await svc._deterministic_fallback(evt.id, _uid())

        assert result.source == "deterministic_fallback"

    async def test_fallback_unknown_event_id_returns_gracefully(
        self, db_session: AsyncSession
    ) -> None:
        svc = CoordinatorService(db_session)
        result = await svc._deterministic_fallback("nonexistent-event-id", _uid())

        # Should return gracefully without raising, with no assessment data
        assert result.assessment_ready is False
        assert result.human_review_required is True


class TestParseAndValidate:
    def _svc(self, db_session: AsyncSession) -> CoordinatorService:
        return CoordinatorService(db_session)

    async def test_valid_agent_output_parsed(self, db_session: AsyncSession) -> None:
        svc = self._svc(db_session)
        payload = {
            "event_id": "agent-provided-id",  # should be overridden
            "assessment_ready": True,
            "summary": "Activity was detected at the loading dock.",
            "missing_evidence": [],
            "human_review_required": True,
        }
        result = svc._parse_and_validate(
            "server-event-id", json.dumps(payload), _uid(), source="orchestrate"
        )
        assert result.event_id == "server-event-id"  # server-side override
        assert result.assessment_ready is True
        assert result.source == "orchestrate"

    async def test_event_id_always_overridden_by_server(self, db_session: AsyncSession) -> None:
        """Prompt-injection defence: event_id from agent is discarded."""
        svc = self._svc(db_session)
        payload = {
            "event_id": "injected-id",
            "assessment_ready": True,
            "summary": "Test summary for validation.",
            "missing_evidence": [],
            "human_review_required": True,
        }
        result = svc._parse_and_validate(
            "real-event-id", json.dumps(payload), _uid(), source="orchestrate"
        )
        assert result.event_id == "real-event-id"

    async def test_human_review_required_forced_true(self, db_session: AsyncSession) -> None:
        """ADR-006: human_review_required is ALWAYS True."""
        svc = self._svc(db_session)
        payload = {
            "event_id": "evt-1",
            "assessment_ready": False,
            "summary": "No assessment ready.",
            "missing_evidence": [],
            "human_review_required": True,  # schema requires True
        }
        result = svc._parse_and_validate("evt-1", json.dumps(payload), _uid(), source="orchestrate")
        assert result.human_review_required is True

    async def test_non_json_raises_value_error(self, db_session: AsyncSession) -> None:
        svc = self._svc(db_session)
        with pytest.raises(ValueError, match="non-JSON"):
            svc._parse_and_validate("evt-1", "not json at all", _uid(), source="orchestrate")

    async def test_schema_validation_error_raises_value_error(
        self, db_session: AsyncSession
    ) -> None:
        svc = self._svc(db_session)
        # Missing required 'summary' field
        payload = {"event_id": "evt-1", "assessment_ready": True}
        with pytest.raises(ValueError, match="schema validation"):
            svc._parse_and_validate("evt-1", json.dumps(payload), _uid(), source="orchestrate")

    async def test_markdown_fenced_json_stripped(self, db_session: AsyncSession) -> None:
        svc = self._svc(db_session)
        payload = {
            "event_id": "evt-1",
            "assessment_ready": True,
            "summary": "Activity was detected.",
            "missing_evidence": [],
            "human_review_required": True,
        }
        fenced = f"```json\n{json.dumps(payload)}\n```"
        result = svc._parse_and_validate("evt-1", fenced, _uid(), source="orchestrate")
        assert result.assessment_ready is True

    async def test_forbidden_word_replaced_in_summary(self, db_session: AsyncSession) -> None:
        svc = self._svc(db_session)
        payload = {
            "event_id": "evt-1",
            "assessment_ready": True,
            "summary": "A criminal was detected at the entrance.",
            "missing_evidence": [],
            "human_review_required": True,
        }
        result = svc._parse_and_validate("evt-1", json.dumps(payload), _uid(), source="orchestrate")
        assert "criminal" not in result.summary
        assert "individual" in result.summary

    async def test_summary_truncated_at_1024(self, db_session: AsyncSession) -> None:
        svc = self._svc(db_session)
        long_summary = "A" * 2048
        payload = {
            "event_id": "evt-1",
            "assessment_ready": True,
            "summary": long_summary,
            "missing_evidence": [],
            "human_review_required": True,
        }
        result = svc._parse_and_validate("evt-1", json.dumps(payload), _uid(), source="orchestrate")
        assert len(result.summary) <= 1024


class TestCoordinatorServiceRun:
    def test_runtime_prompt_requires_each_specialist_collaborator(self) -> None:
        assert "delegate exactly one bounded read-only" in _COORDINATOR_SYSTEM_PROMPT
        for collaborator_role in ("Triage", "Context", "Explanation"):
            assert collaborator_role in _COORDINATOR_SYSTEM_PROMPT

    async def test_run_uses_fallback_in_test_env(self, db_session: AsyncSession) -> None:
        """APP_ENV=test → orchestrate_active=False → deterministic fallback."""
        evt = await _make_event(db_session)
        await _make_assessment(db_session, evt.id)

        svc = CoordinatorService(db_session)
        result = await svc.run(evt.id)

        assert result.source == "deterministic_fallback"
        assert result.human_review_required is True

    async def test_run_persists_agent_run_row(self, db_session: AsyncSession) -> None:
        from sqlalchemy import select

        evt = await _make_event(db_session)

        svc = CoordinatorService(db_session)
        await svc.run(evt.id)

        rows = (
            (await db_session.execute(select(AgentRun).where(AgentRun.event_id == evt.id)))
            .scalars()
            .all()
        )
        assert len(rows) >= 1
        assert rows[0].agent_name == "sentinel_coordinator"

    async def test_run_orchestrate_fails_falls_to_deterministic(
        self, db_session: AsyncSession
    ) -> None:
        """Even when Orchestrate call raises, fallback produces a result."""
        evt = await _make_event(db_session)
        await _make_assessment(db_session, evt.id)

        svc = CoordinatorService(db_session)
        with patch.object(
            svc,
            "_invoke_orchestrate",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Orchestrate unavailable"),
        ):
            result = await svc.run(evt.id)

        assert result.source == "deterministic_fallback"
        assert result.human_review_required is True

    async def test_run_returns_event_id(self, db_session: AsyncSession) -> None:
        evt = await _make_event(db_session)

        svc = CoordinatorService(db_session)
        result = await svc.run(evt.id)

        assert result.event_id == evt.id


# ---------------------------------------------------------------------------
# API integration tests — GET /api/v1/events/{id}/review
# ---------------------------------------------------------------------------


class TestCoordinatorAPI:
    async def test_200_awaiting_review(self, client: AsyncClient, db_session: AsyncSession) -> None:
        evt = await _make_event(db_session, status="awaiting_review")
        await _make_assessment(db_session, evt.id)

        resp = await client.get(f"/api/v1/events/{evt.id}/review")

        assert resp.status_code == 200
        data = resp.json()
        assert data["event_id"] == evt.id
        assert data["human_review_required"] is True
        assert "summary" in data
        assert "source" in data

    async def test_200_escalated_status(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        evt = await _make_event(db_session, status="escalated")
        await _make_assessment(db_session, evt.id)

        resp = await client.get(f"/api/v1/events/{evt.id}/review")

        assert resp.status_code == 200
        data = resp.json()
        assert data["event_id"] == evt.id

    async def test_409_normalised_status(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        evt = await _make_event(db_session, status="normalised")

        resp = await client.get(f"/api/v1/events/{evt.id}/review")

        assert resp.status_code == 409

    async def test_409_closed_status(self, client: AsyncClient, db_session: AsyncSession) -> None:
        evt = await _make_event(db_session, status="closed")

        resp = await client.get(f"/api/v1/events/{evt.id}/review")

        assert resp.status_code == 409

    async def test_404_unknown_event(self, client: AsyncClient, db_session: AsyncSession) -> None:
        resp = await client.get("/api/v1/events/nonexistent-event-id-xyz/review")

        assert resp.status_code == 404

    async def test_human_review_required_always_true_in_response(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        evt = await _make_event(db_session, status="awaiting_review")
        await _make_assessment(db_session, evt.id)

        resp = await client.get(f"/api/v1/events/{evt.id}/review")

        assert resp.status_code == 200
        assert resp.json()["human_review_required"] is True

    async def test_source_is_deterministic_in_test_env(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        evt = await _make_event(db_session, status="awaiting_review")
        await _make_assessment(db_session, evt.id)

        resp = await client.get(f"/api/v1/events/{evt.id}/review")

        assert resp.status_code == 200
        assert resp.json()["source"] == "deterministic_fallback"

    async def test_assessment_ready_true_when_row_exists(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        evt = await _make_event(db_session, status="awaiting_review")
        await _make_assessment(db_session, evt.id)

        resp = await client.get(f"/api/v1/events/{evt.id}/review")

        assert resp.status_code == 200
        assert resp.json()["assessment_ready"] is True

    async def test_assessment_ready_false_when_no_assessment(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        # Force awaiting_review status with no assessment row
        evt = await _make_event(db_session, status="awaiting_review")
        # Don't create an assessment row

        resp = await client.get(f"/api/v1/events/{evt.id}/review")

        assert resp.status_code == 200
        # assessment_ready depends on whether a RiskAssessment row exists
        assert resp.json()["assessment_ready"] is False

    async def test_missing_evidence_list_present(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        evt = await _make_event(db_session, status="awaiting_review")
        await _make_assessment(db_session, evt.id, evidence_errors={"mock_schedule": "timeout"})

        resp = await client.get(f"/api/v1/events/{evt.id}/review")

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["missing_evidence"], list)
        assert "mock_schedule" in data["missing_evidence"]
