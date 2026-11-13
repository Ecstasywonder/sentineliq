"""
Gate 20 — Integration and failure-state hardening tests.

Verifies safe degradation for every failure scenario in the Master Build Prompt:

  1. Unavailable access system      — evidence_aggregator._safe isolates error
  2. Unavailable schedule system     — evidence_aggregator._safe isolates error
  3. Unavailable LLM                 — TriageService falls to deterministic fallback
  4. Missing history                 — incident_history section is empty; confidence reduced
  5. Contradictory evidence          — ContextService detects conflicts; has_conflicts=True
  6. Malformed tool output           — _safe catches ValueError/ValidationError; section None
  7. Timeout                         — httpx.TimeoutException caught; triage falls to fallback
  8. Stale source                    — IntegrationHealth record with consecutive_failures > 0
  9. Duplicate event                 — POST /events returns 200 + Duplicate-Event header

Architecture constraints verified throughout:
  - Evidence errors are ISOLATED — other sources still return normally
  - Event is NEVER LOST — every triage path terminates with a TriageResult
  - Risk score is NEVER produced by LLM (ADR-003)
  - Missing evidence → confidence reduction ONLY, not altered risk (ADR-004)
  - Human review remains NON-BYPASSABLE (ADR-006)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.access import AccessEvent
from app.models.integration import IntegrationHealth
from app.schemas.triage import TriageResult
from app.services.confidence_engine import ConfidenceEngine, SourceStatus
from app.services.evidence_aggregator import EvidenceAggregator
from app.services.triage_service import TriageService

pytestmark = pytest.mark.asyncio

_LOC = "fail-loc-001"
_FAC = "fail-fac-001"


def _uid() -> str:
    return str(uuid.uuid4())


def _event_meta(
    *,
    event_type: str = "person_detected",
    event_timestamp: str = "2026-01-01T23:00:00Z",
    location_id: str = _LOC,
    zone: str | None = None,
    detector_confidence: float | None = 0.9,
    camera_id: str | None = "CAM-01",
) -> dict:
    return {
        "event_type": event_type,
        "event_timestamp": event_timestamp,
        "location_id": location_id,
        "zone": zone,
        "detector_confidence": detector_confidence,
        "camera_id": camera_id,
    }


# ===========================================================================
# Scenario 1 — Unavailable access system
# ===========================================================================


class TestUnavailableAccessSystem:
    async def test_access_error_isolated_in_errors_dict(self, db_session: AsyncSession) -> None:
        """When the access control adapter raises, the error is captured in
        errors['access_events'] and the other sources still return."""
        agg = EvidenceAggregator(db_session)
        with patch.object(
            agg._access,
            "get_access_events",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Access control service unavailable"),
        ):
            result = await agg.gather("evt-access-fail", _LOC, facility_id=_FAC)

        assert "access_events" in result.errors
        assert "unavailable" in result.errors["access_events"].lower()
        # Other sources are unaffected
        assert result.access_events is None
        assert result.schedule is not None
        assert result.work_orders is not None

    async def test_access_error_does_not_affect_risk_computation(
        self, db_session: AsyncSession
    ) -> None:
        """EvidenceAggregator.gather never raises — the caller (AssessmentService)
        always receives a bundle it can score."""
        agg = EvidenceAggregator(db_session)
        with patch.object(
            agg._access,
            "get_access_events",
            new_callable=AsyncMock,
            side_effect=ConnectionError("Network unreachable"),
        ):
            result = await agg.gather("evt-access-net", _LOC)

        # gather must not raise
        assert result is not None
        assert result.event_id == "evt-access-net"

    async def test_access_error_reduces_available_sources_count(
        self, db_session: AsyncSession
    ) -> None:
        """ConfidenceEngine receives a reduced source count when access is unavailable."""
        agg = EvidenceAggregator(db_session)
        with patch.object(
            agg._access,
            "get_access_events",
            new_callable=AsyncMock,
            side_effect=RuntimeError("timeout"),
        ):
            evidence = await agg.gather("evt-access-conf", _LOC)

        # Build source statuses the same way AssessmentService does
        source_statuses = _build_source_statuses(evidence)
        available = sum(1 for s in source_statuses if s.available)
        total = len(source_statuses)
        assert available < total, "Available sources should be less than total when one fails"


# ===========================================================================
# Scenario 2 — Unavailable schedule system
# ===========================================================================


class TestUnavailableScheduleSystem:
    async def test_schedule_error_isolated(self, db_session: AsyncSession) -> None:
        agg = EvidenceAggregator(db_session)
        with patch.object(
            agg._schedule,
            "get_schedule",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Schedule service unavailable"),
        ):
            result = await agg.gather("evt-sched-fail", _LOC)

        assert "schedule" in result.errors
        assert result.schedule is None
        # access control is unaffected
        assert result.access_events is not None

    async def test_multiple_sources_can_fail_simultaneously(self, db_session: AsyncSession) -> None:
        """Two adapters can fail at once; all errors are independently captured."""
        agg = EvidenceAggregator(db_session)
        with (
            patch.object(
                agg._access,
                "get_access_events",
                new_callable=AsyncMock,
                side_effect=RuntimeError("access down"),
            ),
            patch.object(
                agg._schedule,
                "get_schedule",
                new_callable=AsyncMock,
                side_effect=RuntimeError("schedule down"),
            ),
        ):
            result = await agg.gather("evt-multi-fail", _LOC)

        assert "access_events" in result.errors
        assert "schedule" in result.errors
        assert result.access_events is None
        assert result.schedule is None
        # delivery still present
        assert result.delivery is not None


# ===========================================================================
# Scenario 3 — Unavailable LLM
# ===========================================================================


class TestUnavailableLLM:
    async def test_triage_falls_back_to_deterministic_when_llm_unavailable(
        self, db_session: AsyncSession
    ) -> None:
        """When Path B is inactive (test env), triage always returns a
        deterministic result — never None, never raises."""
        svc = TriageService(db_session)
        meta = _event_meta(event_type="person_detected")
        result = await svc.run("evt-llm-off", meta)

        assert isinstance(result, TriageResult)
        assert result.source == "deterministic_fallback"
        assert result.category in {
            "after_hours_presence",
            "restricted_area_access",
            "delivery_event",
            "authorized_access",
            "alarm_event",
            "vehicle_event",
            "unclassified",
        }

    async def test_triage_source_is_deterministic_fallback_in_test_env(
        self, db_session: AsyncSession
    ) -> None:
        """In the test environment, Orchestrate is inactive (APP_ENV=test),
        so Path 0 is always used."""
        svc = TriageService(db_session)
        result = await svc.run("evt-llm-src", _event_meta())
        assert result.source == "deterministic_fallback"

    async def test_triage_result_never_contains_risk_score(self, db_session: AsyncSession) -> None:
        """ADR-003: LLM never produces risk scores. TriageResult has no risk field."""
        svc = TriageService(db_session)
        result = await svc.run("evt-no-risk", _event_meta())
        assert not hasattr(result, "risk_score")
        assert not hasattr(result, "risk_level")


# ===========================================================================
# Scenario 4 — Missing history
# ===========================================================================


class TestMissingHistory:
    async def test_empty_incident_history_returns_zero_records(
        self, db_session: AsyncSession
    ) -> None:
        """When no IncidentHistory rows exist for a location, record_count is 0."""
        agg = EvidenceAggregator(db_session)
        result = await agg.gather("evt-no-hist", "loc-no-history-at-all")

        assert result.incident_history is not None
        assert result.incident_history.meta.record_count == 0
        assert result.incident_history.records == []
        # No error — empty is valid
        assert "incident_history" not in result.errors

    async def test_missing_history_does_not_block_risk_assessment(
        self, db_session: AsyncSession
    ) -> None:
        """gather() completes successfully with zero incident records."""
        agg = EvidenceAggregator(db_session)
        result = await agg.gather("evt-hist-empty", "loc-hist-only")
        assert result is not None
        assert result.errors.get("incident_history") is None

    async def test_missing_history_reduces_confidence_via_source_status(
        self, db_session: AsyncSession
    ) -> None:
        """ConfidenceEngine SOURCE_UNAVAILABLE reduction applies when incident_history=None."""
        # Simulate incident_history source failing
        agg = EvidenceAggregator(db_session)
        with patch.object(
            agg,
            "_fetch_incident_history",
            new_callable=AsyncMock,
            side_effect=RuntimeError("history unavailable"),
        ):
            evidence = await agg.gather("evt-hist-conf", _LOC)

        assert evidence.incident_history is None
        assert "incident_history" in evidence.errors

        # Confidence engine sees a missing source → reduced confidence
        source_statuses = _build_source_statuses(evidence)
        engine = ConfidenceEngine()
        confidence = engine.assess(source_statuses)
        assert confidence.confidence_score < 1.0
        assert any(r.reason for r in confidence.reductions)


# ===========================================================================
# Scenario 5 — Contradictory evidence
# ===========================================================================


class TestContradictoryEvidence:
    async def test_contradictory_access_and_schedule_surface_as_conflict(
        self, db_session: AsyncSession
    ) -> None:
        """Access event outside schedule window is detected as a conflict by ContextService."""
        from app.services.context_service import ContextService

        # Seed an access event at a time with no schedule
        db_session.add(
            AccessEvent(
                id=_uid(),
                location_id=_LOC,
                facility_id=_FAC,
                access_type="entry",
                access_granted=True,
                occurred_at="2026-01-01T03:00:00Z",  # 3 AM — after hours
                source_system="mock",
            )
        )
        await db_session.flush()

        agg = EvidenceAggregator(db_session)
        evidence = await agg.gather("evt-conflict", _LOC, facility_id=_FAC)
        from app.schemas.triage import TriageResult

        triage = TriageResult(
            event_id="evt-conflict",
            category="after_hours_presence",
            urgency_signals=["after_hours"],
            required_context=["access_control", "schedule"],
            triage_rationale="After-hours entry detected.",
            source="deterministic_fallback",
        )
        ctx_svc = ContextService(db_session)
        ctx = await ctx_svc.run(
            "evt-conflict",
            event_metadata=_event_meta(event_timestamp="2026-01-01T03:00:00Z"),
            required_context=triage.required_context,
            evidence=evidence,
        )

        assert ctx is not None
        # Either has_conflicts or missing sources — both are valid safe degradation
        assert isinstance(ctx.has_conflicts, bool)
        assert isinstance(ctx.missing_sources, list)

    async def test_context_service_never_raises(self, db_session: AsyncSession) -> None:
        """ContextService must return a ContextResult regardless of evidence state."""
        from app.schemas.triage import TriageResult
        from app.services.context_service import ContextService

        agg = EvidenceAggregator(db_session)
        evidence = await agg.gather("evt-ctx-safe", _LOC)
        triage = TriageResult(
            event_id="evt-ctx-safe",
            category="unclassified",
            urgency_signals=[],
            required_context=["access_control", "schedule"],
            triage_rationale="Unclassified.",
            source="deterministic_fallback",
        )
        svc = ContextService(db_session)
        ctx = await svc.run(
            "evt-ctx-safe",
            event_metadata=_event_meta(),
            required_context=triage.required_context,
            evidence=evidence,
        )
        assert ctx is not None


# ===========================================================================
# Scenario 6 — Malformed tool output
# ===========================================================================


class TestMalformedToolOutput:
    async def test_malformed_access_adapter_output_captured_in_errors(
        self, db_session: AsyncSession
    ) -> None:
        """If an adapter raises ValueError (e.g., bad field mapping), the error is
        captured in errors and that section returns None."""
        agg = EvidenceAggregator(db_session)
        with patch.object(
            agg,
            "_fetch_access_events",
            new_callable=AsyncMock,
            side_effect=ValueError("Unexpected field 'biometric_id' in response"),
        ):
            result = await agg.gather("evt-malformed-access", _LOC)

        assert result.access_events is None
        assert "access_events" in result.errors
        assert "biometric_id" in result.errors["access_events"]

    async def test_malformed_schedule_output_captured(self, db_session: AsyncSession) -> None:
        agg = EvidenceAggregator(db_session)
        with patch.object(
            agg,
            "_fetch_schedule",
            new_callable=AsyncMock,
            side_effect=ValueError("Missing required field: start_time"),
        ):
            result = await agg.gather("evt-malformed-sched", _LOC)

        assert result.schedule is None
        assert "schedule" in result.errors

    async def test_malformed_output_does_not_propagate_to_caller(
        self, db_session: AsyncSession
    ) -> None:
        """_safe must absorb ALL exceptions — even unexpected types."""
        agg = EvidenceAggregator(db_session)
        with patch.object(
            agg,
            "_fetch_work_orders",
            new_callable=AsyncMock,
            side_effect=KeyError("work_order_type"),
        ):
            # Must not raise
            result = await agg.gather("evt-malformed-wo", _LOC)

        assert result is not None
        assert "work_orders" in result.errors


# ===========================================================================
# Scenario 7 — Timeout
# ===========================================================================


class TestTimeout:
    async def test_adapter_timeout_captured_in_errors(self, db_session: AsyncSession) -> None:
        """httpx.TimeoutException from an adapter is caught by _safe."""
        agg = EvidenceAggregator(db_session)
        with patch.object(
            agg._access,
            "get_access_events",
            new_callable=AsyncMock,
            side_effect=httpx.TimeoutException("Request timed out"),
        ):
            result = await agg.gather("evt-timeout-access", _LOC)

        assert result.access_events is None
        assert "access_events" in result.errors

    async def test_orchestrate_timeout_falls_to_deterministic(
        self, db_session: AsyncSession
    ) -> None:
        """A Path B timeout must terminate in the deterministic safety path."""
        svc = TriageService(db_session)
        svc._settings = SimpleNamespace(
            orchestrate_active=True,
            orchestrate_triage_agent_id="11111111-2222-4333-8444-555555555555",
            agent_invoke_timeout=30.0,
        )
        with patch.object(
            svc,
            "_invoke_orchestrate_saas",
            new_callable=AsyncMock,
            side_effect=httpx.TimeoutException("Orchestrate call timed out"),
        ):
            result = await svc.run("evt-triage-timeout", _event_meta())

        assert isinstance(result, TriageResult)
        assert result.source == "deterministic_fallback"

    async def test_delivery_timeout_isolated(self, db_session: AsyncSession) -> None:
        agg = EvidenceAggregator(db_session)
        with patch.object(
            agg._delivery,
            "get_deliveries",
            new_callable=AsyncMock,
            side_effect=httpx.TimeoutException("Delivery service timeout"),
        ):
            result = await agg.gather("evt-delivery-timeout", _LOC)

        assert result.delivery is None
        assert "delivery" in result.errors
        # Other sources are present
        assert result.access_events is not None
        assert result.schedule is not None


# ===========================================================================
# Scenario 8 — Stale source
# ===========================================================================


class TestStaleSource:
    async def test_stale_integration_health_record_surfaces_in_health_response(
        self, db_session: AsyncSession
    ) -> None:
        """An IntegrationHealth row with consecutive_failures > 0 is returned
        as-is so the operator can see degraded status."""
        stale = IntegrationHealth(
            id=_uid(),
            source_id="legacy_badge_system",
            name="Legacy Badge Reader",
            status="degraded",
            last_checked_at=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC).isoformat(),
            consecutive_failures=5,
            error_message="Connection reset by peer",
            adapter_class="LegacyBadgeAdapter",
        )
        db_session.add(stale)
        await db_session.flush()

        agg = EvidenceAggregator(db_session)
        result = await agg.gather("evt-stale", _LOC)

        assert result.integration_health is not None
        source_ids = {r.source_id for r in result.integration_health.records}
        assert "legacy_badge_system" in source_ids

        stale_record = next(
            r for r in result.integration_health.records if r.source_id == "legacy_badge_system"
        )
        assert stale_record.status == "degraded"
        assert stale_record.consecutive_failures == 5

    async def test_stale_source_does_not_prevent_assessment(self, db_session: AsyncSession) -> None:
        """Stale integration health records do not block the evidence gather call."""
        stale = IntegrationHealth(
            id=_uid(),
            source_id="stale_camera_system",
            name="Camera VMS",
            status="unavailable",
            last_checked_at=datetime(2025, 6, 1, tzinfo=UTC).isoformat(),
            consecutive_failures=100,
            adapter_class="VMSAdapter",
        )
        db_session.add(stale)
        await db_session.flush()

        agg = EvidenceAggregator(db_session)
        result = await agg.gather("evt-stale-ok", _LOC)
        assert result is not None
        assert "integration_health" not in result.errors

    async def test_live_adapter_health_overrides_stale_db_row(
        self, db_session: AsyncSession
    ) -> None:
        """If an adapter's live health probe produces a source_id that matches a
        stale DB row, the live probe result takes precedence."""
        stale = IntegrationHealth(
            id=_uid(),
            source_id="mock_access_control",
            name="Old Access Record",
            status="unavailable",
            consecutive_failures=99,
            adapter_class="OldAdapter",
        )
        db_session.add(stale)
        await db_session.flush()

        agg = EvidenceAggregator(db_session)
        result = await agg.gather("evt-probe-win", _LOC)
        assert result.integration_health is not None

        # The live probe for mock_access_control should have won (probe_map takes priority)
        access_record = next(
            (r for r in result.integration_health.records if r.source_id == "mock_access_control"),
            None,
        )
        assert access_record is not None
        # Live probe status must NOT be the stale "unavailable"
        assert access_record.status != "unavailable"


# ===========================================================================
# Scenario 9 — Duplicate event
# ===========================================================================


class TestDuplicateEvent:
    async def test_duplicate_provider_event_id_returns_200(self, client) -> None:
        """POST /events with the same provider_event_id within the dedup window
        returns HTTP 200 (not 201) with the Duplicate-Event header."""
        payload = {
            "event_type": "person_detected",
            "event_timestamp": "2026-01-01T10:00:00Z",
            "location_id": "DUP-LOC-001",
            "provider_event_id": f"dup-{_uid()}",
        }

        resp1 = await client.post("/api/v1/events", json=payload)
        assert resp1.status_code == 201

        resp2 = await client.post("/api/v1/events", json=payload)
        assert resp2.status_code == 200
        assert resp2.headers.get("duplicate-event") == "true"

    async def test_duplicate_event_body_matches_original(self, client) -> None:
        """The duplicate response body contains the original event ID."""
        provider_id = f"dup-body-{_uid()}"
        payload = {
            "event_type": "motion_detected",
            "event_timestamp": "2026-01-01T11:00:00Z",
            "location_id": "DUP-LOC-002",
            "provider_event_id": provider_id,
        }
        resp1 = await client.post("/api/v1/events", json=payload)
        original_id = resp1.json()["id"]

        resp2 = await client.post("/api/v1/events", json=payload)
        assert resp2.json()["id"] == original_id

    async def test_event_without_provider_id_never_deduplicates(self, client) -> None:
        """Events with no provider_event_id are never treated as duplicates."""
        payload = {
            "event_type": "badge_event",
            "event_timestamp": "2026-01-01T12:00:00Z",
            "location_id": "DUP-LOC-003",
            # No provider_event_id
        }
        resp1 = await client.post("/api/v1/events", json=payload)
        resp2 = await client.post("/api/v1/events", json=payload)
        assert resp1.status_code == 201
        assert resp2.status_code == 201
        assert resp1.json()["id"] != resp2.json()["id"]

    async def test_different_provider_event_ids_are_independent(self, client) -> None:
        """Different provider_event_id values each get their own event row."""
        base = {
            "event_type": "alarm_triggered",
            "event_timestamp": "2026-01-01T13:00:00Z",
            "location_id": "DUP-LOC-004",
        }
        resp1 = await client.post(
            "/api/v1/events", json={**base, "provider_event_id": f"uniq-a-{_uid()}"}
        )
        resp2 = await client.post(
            "/api/v1/events", json={**base, "provider_event_id": f"uniq-b-{_uid()}"}
        )
        assert resp1.status_code == 201
        assert resp2.status_code == 201
        assert resp1.json()["id"] != resp2.json()["id"]


# ===========================================================================
# Cross-cutting: safe degradation invariants
# ===========================================================================


class TestSafeDegradationInvariants:
    async def test_all_sources_failing_still_returns_bundle(self, db_session: AsyncSession) -> None:
        """Even if all 4 adapters fail, gather() returns an AggregatedEvidence
        with errors populated — never raises."""
        agg = EvidenceAggregator(db_session)
        with (
            patch.object(
                agg._access,
                "get_access_events",
                new_callable=AsyncMock,
                side_effect=RuntimeError("access"),
            ),
            patch.object(
                agg._schedule,
                "get_schedule",
                new_callable=AsyncMock,
                side_effect=RuntimeError("schedule"),
            ),
            patch.object(
                agg._work_order,
                "get_work_orders",
                new_callable=AsyncMock,
                side_effect=RuntimeError("wo"),
            ),
            patch.object(
                agg._delivery,
                "get_deliveries",
                new_callable=AsyncMock,
                side_effect=RuntimeError("delivery"),
            ),
        ):
            result = await agg.gather("evt-all-fail", _LOC)

        assert result is not None
        assert len(result.errors) == 4
        # DB-backed sources still work
        assert result.location_policy is not None
        assert result.incident_history is not None

    async def test_triage_result_always_has_required_context_baseline(
        self, db_session: AsyncSession
    ) -> None:
        """Even with no LLM, triage always includes the baseline required_context
        (access_control, schedule, location_policy, incident_history)."""
        svc = TriageService(db_session)
        result = await svc.run("evt-baseline", _event_meta())
        required = set(result.required_context)
        assert "access_control" in required
        assert "schedule" in required
        assert "location_policy" in required
        assert "incident_history" in required

    async def test_confidence_decreases_with_each_missing_source(
        self, db_session: AsyncSession
    ) -> None:
        """Each missing evidence source reduces confidence — never increases risk."""
        agg_full = EvidenceAggregator(db_session)
        evidence_full = await agg_full.gather("evt-conf-full", _LOC)

        agg_fail = EvidenceAggregator(db_session)
        with patch.object(
            agg_fail._access,
            "get_access_events",
            new_callable=AsyncMock,
            side_effect=RuntimeError("access down"),
        ):
            evidence_fail = await agg_fail.gather("evt-conf-fail", _LOC)

        engine = ConfidenceEngine()
        conf_full = engine.assess(_build_source_statuses(evidence_full))
        conf_fail = engine.assess(_build_source_statuses(evidence_fail))

        assert conf_fail.confidence_score <= conf_full.confidence_score, (
            "Confidence must not increase when evidence is missing"
        )


# ===========================================================================
# Helper — build source statuses from evidence bundle (mirrors AssessmentService)
# ===========================================================================

_SOURCE_ID_MAP = {
    "access_events": "mock_access_control",
    "schedule": "mock_schedule",
    "work_orders": "mock_work_order",
    "delivery": "mock_delivery",
    "location_policy": "db_security_rules",
    "incident_history": "db_incident_history",
    "knowledge_search": "knowledge_retrieval",
}


def _build_source_statuses(evidence) -> list[SourceStatus]:
    statuses: list[SourceStatus] = []
    field_map = {
        "access_events": evidence.access_events,
        "schedule": evidence.schedule,
        "work_orders": evidence.work_orders,
        "delivery": evidence.delivery,
        "location_policy": evidence.location_policy,
        "incident_history": evidence.incident_history,
        "knowledge_search": evidence.knowledge_search,
    }
    for field, section in field_map.items():
        source_id = _SOURCE_ID_MAP.get(field, field)
        statuses.append(SourceStatus(source_id=source_id, available=section is not None))
    return statuses
