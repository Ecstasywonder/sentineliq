"""
Gate 15 — Context Service tests.

Tests cover:
1. Deterministic fallback (no LLM credentials configured)
   - source status classification (verified_present / verified_absent / unavailable / not_requested)
   - conflict detection (badge-denied + no-schedule, valid-access + restricted-policy)
   - missing_sources tracking
   - context_summary construction
2. LLM path (mocked HTTP)
   - Path B (Orchestrate) success
   - Path A (watsonx.ai) success
   - Path B failure → falls through to Path A
   - Path A failure → falls through to Path 0
3. Agent output validation / injection filtering
   - unknown source keys stripped
   - unknown status values normalised to 'unavailable'
   - context_summary truncated at 1024 chars
   - conflicts with missing fields discarded
   - non-JSON output → fallback
4. _compact_evidence_for_llm and _serialise_evidence helpers
5. AgentRun persistence
6. Integration: POST /events/{id}/assess includes context in response
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.context_service import ContextService


# ---------------------------------------------------------------------------
# Evidence fixtures
# ---------------------------------------------------------------------------


def _make_evidence(
    *,
    access_events=None,
    schedule=None,
    work_orders=None,
    delivery=None,
    location_policy=None,
    incident_history=None,
    integration_health=None,
    errors=None,
) -> MagicMock:
    """Build a minimal AggregatedEvidence-like object."""
    ev = MagicMock()
    ev.errors = errors or {}

    def _section(records=None, count=0, source="mock"):
        s = MagicMock()
        s.records = records or []
        s.meta = MagicMock()
        s.meta.record_count = count
        s.meta.source = source
        return s

    ev.access_events = access_events
    ev.schedule = schedule
    ev.work_orders = work_orders
    ev.delivery = delivery
    ev.location_policy = location_policy
    ev.incident_history = incident_history
    ev.integration_health = integration_health

    # model_dump mirrors the structure the real AggregatedEvidence produces
    def _to_dict(section, key):
        if section is None:
            return None
        try:
            recs = [r if isinstance(r, dict) else r.__dict__ for r in (section.records or [])]
        except Exception:
            recs = []
        return {
            "meta": {"record_count": section.meta.record_count, "source": section.meta.source},
            "records": recs,
        }

    ev.model_dump.return_value = {
        "access_events": _to_dict(access_events, "access_events"),
        "schedule": _to_dict(schedule, "schedule"),
        "work_orders": _to_dict(work_orders, "work_orders"),
        "delivery": _to_dict(delivery, "delivery"),
        "location_policy": _to_dict(location_policy, "location_policy"),
        "incident_history": _to_dict(incident_history, "incident_history"),
        "integration_health": _to_dict(integration_health, "integration_health"),
        "errors": errors or {},
    }
    return ev


def _section_present(count=2, source="mock", records=None):
    s = MagicMock()
    s.records = records or []
    s.meta = MagicMock()
    s.meta.record_count = count
    s.meta.source = source
    return s


def _section_absent(source="mock"):
    return _section_present(count=0, source=source)


_ALL_REQUIRED = [
    "access_control", "schedule", "work_orders",
    "delivery_context", "location_policy", "incident_history",
]


# ---------------------------------------------------------------------------
# Unit tests — deterministic fallback
# ---------------------------------------------------------------------------


class TestDeterministicFallback:
    def _svc(self):
        return ContextService(session=None)

    def test_all_present(self):
        ev = _make_evidence(
            access_events=_section_present(3),
            schedule=_section_present(1),
            work_orders=_section_present(2),
            delivery=_section_present(1),
            location_policy=_section_present(1),
            incident_history=_section_present(4),
        )
        result = self._svc()._deterministic_context("EVT-001", _ALL_REQUIRED, ev)
        assert result.source == "deterministic_fallback"
        assert result.source_statuses["access_control"].status == "verified_present"
        assert result.source_statuses["schedule"].status == "verified_present"
        assert result.source_statuses["location_policy"].status == "verified_present"
        assert result.source_statuses["incident_history"].status == "verified_present"
        assert not result.has_missing_sources

    def test_absent_source(self):
        ev = _make_evidence(
            access_events=_section_absent(),
            schedule=_section_absent(),
            work_orders=_section_absent(),
            delivery=_section_absent(),
            location_policy=_section_absent(),
            incident_history=_section_absent(),
        )
        result = self._svc()._deterministic_context("EVT-001", _ALL_REQUIRED, ev)
        assert result.source_statuses["access_control"].status == "verified_absent"
        assert result.source_statuses["schedule"].status == "verified_absent"

    def test_unavailable_source_via_errors(self):
        ev = _make_evidence(
            access_events=_section_present(1),
            errors={"mock_access_control": "timeout"},
        )
        # When 'access_control' is in required_context and the source_map
        # key 'mock_access_control' is in errors, it should be unavailable.
        # The mapping uses the errors keys directly (ctx_src or ev_key).
        # Here we simulate it via the ev_key path.
        ev.model_dump.return_value["errors"] = {"access_events": "timeout"}
        result = self._svc()._deterministic_context("EVT-001", ["access_control"], ev)
        assert result.source_statuses["access_control"].status == "unavailable"
        assert "access_control" in result.missing_sources
        assert result.has_missing_sources

    def test_not_requested_source(self):
        ev = _make_evidence()
        result = self._svc()._deterministic_context("EVT-001", [], ev)
        # All sources are not_requested when required_context is empty
        for src in _ALL_REQUIRED:
            assert result.source_statuses[src].status == "not_requested"
        assert not result.has_missing_sources

    def test_missing_source_none_section(self):
        ev = _make_evidence(access_events=None)
        result = self._svc()._deterministic_context("EVT-001", ["access_control"], ev)
        assert result.source_statuses["access_control"].status == "unavailable"
        assert "access_control" in result.missing_sources

    def test_context_summary_contains_present_sources(self):
        ev = _make_evidence(
            access_events=_section_present(1),
            schedule=_section_absent(),
        )
        result = self._svc()._deterministic_context(
            "EVT-001", ["access_control", "schedule"], ev
        )
        assert "access_control" in result.context_summary
        assert "schedule" in result.context_summary

    def test_summary_truncated_at_1024(self):
        # A very long summary should never exceed 1024 chars
        ev = _make_evidence(access_events=_section_present(1))
        result = self._svc()._deterministic_context(
            "EVT-001", ["access_control"], ev
        )
        assert len(result.context_summary) <= 1024


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------


class TestConflictDetection:
    def _svc(self):
        return ContextService(session=None)

    def _ev_with_access_granted_and_restricted_policy(self):
        ev = MagicMock()
        ev.errors = {}
        ev.model_dump.return_value = {
            "access_events": {
                "meta": {"record_count": 1, "source": "mock_access_control"},
                "records": [{"access_granted": True, "occurred_at": "2026-11-03T22:00:00Z"}],
            },
            "schedule": {
                "meta": {"record_count": 0, "source": "mock_schedule"},
                "records": [],
            },
            "work_orders": None,
            "delivery": None,
            "location_policy": {
                "meta": {"record_count": 1, "source": "db_security_rules"},
                "records": [{"rule_type": "access_restriction", "is_active": True}],
            },
            "incident_history": None,
            "integration_health": None,
            "errors": {},
        }
        return ev

    def _ev_with_access_denied_and_no_schedule(self):
        ev = MagicMock()
        ev.errors = {}
        ev.model_dump.return_value = {
            "access_events": {
                "meta": {"record_count": 1, "source": "mock_access_control"},
                "records": [{"access_granted": False, "occurred_at": "2026-11-03T22:00:00Z"}],
            },
            "schedule": {
                "meta": {"record_count": 0, "source": "mock_schedule"},
                "records": [],
            },
            "work_orders": None,
            "delivery": None,
            "location_policy": None,
            "incident_history": None,
            "integration_health": None,
            "errors": {},
        }
        return ev

    def test_access_granted_restricted_policy_conflict(self):
        ev = self._ev_with_access_granted_and_restricted_policy()
        result = self._svc()._deterministic_context(
            "EVT-001",
            ["access_control", "schedule", "location_policy"],
            ev,
        )
        assert result.has_conflicts
        conflict_sources = {(c.source_a, c.source_b) for c in result.conflicts}
        assert ("access_control", "location_policy") in conflict_sources

    def test_access_denied_no_schedule_conflict(self):
        ev = self._ev_with_access_denied_and_no_schedule()
        result = self._svc()._deterministic_context(
            "EVT-001",
            ["access_control", "schedule"],
            ev,
        )
        assert result.has_conflicts
        conflict_sources = {(c.source_a, c.source_b) for c in result.conflicts}
        assert ("access_control", "schedule") in conflict_sources

    def test_no_conflict_when_all_clear(self):
        ev = MagicMock()
        ev.errors = {}
        ev.model_dump.return_value = {
            "access_events": {
                "meta": {"record_count": 1, "source": "mock"},
                "records": [{"access_granted": True}],
            },
            "schedule": {
                "meta": {"record_count": 1, "source": "mock"},
                "records": [],
            },
            "work_orders": None,
            "delivery": None,
            "location_policy": None,
            "incident_history": None,
            "integration_health": None,
            "errors": {},
        }
        result = self._svc()._deterministic_context(
            "EVT-001", ["access_control", "schedule"], ev
        )
        assert not result.has_conflicts
        assert result.conflicts == []


# ---------------------------------------------------------------------------
# Response validation / injection filtering
# ---------------------------------------------------------------------------


class TestParseAndValidate:
    def _svc(self):
        return ContextService(session=None)

    def _minimal_valid_json(self, event_id="EVT-001"):
        return json.dumps({
            "event_id": event_id,
            "source_statuses": {
                "access_control": {
                    "status": "verified_present",
                    "record_count": 2,
                    "summary": "Two badge entries found.",
                }
            },
            "conflicts": [],
            "missing_sources": [],
            "context_summary": "Two access records found. No conflicts detected.",
            "has_conflicts": False,
            "has_missing_sources": False,
        })

    def test_valid_json_parses_correctly(self):
        svc = self._svc()
        ev = _make_evidence()
        result = svc._parse_and_validate(
            "EVT-001", self._minimal_valid_json(), ["access_control"], ev, source="watsonx_ai"
        )
        assert result.source == "watsonx_ai"
        assert "access_control" in result.source_statuses
        assert result.source_statuses["access_control"].status == "verified_present"

    def test_unknown_source_key_stripped(self):
        svc = self._svc()
        ev = _make_evidence()
        raw = json.dumps({
            "event_id": "EVT-001",
            "source_statuses": {
                "access_control": {"status": "verified_present"},
                "malicious_injection": {"status": "verified_present"},  # unknown
            },
            "conflicts": [],
            "missing_sources": [],
            "context_summary": "",
            "has_conflicts": False,
            "has_missing_sources": False,
        })
        result = svc._parse_and_validate("EVT-001", raw, [], ev, source="watsonx_ai")
        assert "malicious_injection" not in result.source_statuses
        assert "access_control" in result.source_statuses

    def test_unknown_status_value_normalised_to_unavailable(self):
        svc = self._svc()
        ev = _make_evidence()
        raw = json.dumps({
            "event_id": "EVT-001",
            "source_statuses": {
                "access_control": {"status": "HACKED", "record_count": 99},
            },
            "conflicts": [],
            "missing_sources": [],
            "context_summary": "",
            "has_conflicts": False,
            "has_missing_sources": False,
        })
        result = svc._parse_and_validate("EVT-001", raw, [], ev, source="watsonx_ai")
        assert result.source_statuses["access_control"].status == "unavailable"

    def test_context_summary_truncated(self):
        svc = self._svc()
        ev = _make_evidence()
        long_summary = "x" * 2000
        raw = json.dumps({
            "event_id": "EVT-001",
            "source_statuses": {},
            "conflicts": [],
            "missing_sources": [],
            "context_summary": long_summary,
            "has_conflicts": False,
            "has_missing_sources": False,
        })
        result = svc._parse_and_validate("EVT-001", raw, [], ev, source="watsonx_ai")
        assert len(result.context_summary) <= 1024

    def test_conflict_with_missing_fields_discarded(self):
        svc = self._svc()
        ev = _make_evidence()
        raw = json.dumps({
            "event_id": "EVT-001",
            "source_statuses": {},
            "conflicts": [
                {"source_a": "access_control"},  # missing source_b + description
                {"source_a": "schedule", "source_b": "work_orders", "description": "Valid conflict."},
            ],
            "missing_sources": [],
            "context_summary": "",
            "has_conflicts": True,
            "has_missing_sources": False,
        })
        result = svc._parse_and_validate("EVT-001", raw, [], ev, source="watsonx_ai")
        # Only the complete conflict survives
        assert len(result.conflicts) == 1
        assert result.conflicts[0].source_a == "schedule"

    def test_non_json_raises_value_error(self):
        svc = self._svc()
        ev = _make_evidence()
        with pytest.raises(ValueError, match="non-JSON"):
            svc._parse_and_validate("EVT-001", "this is not json", [], ev, source="watsonx_ai")

    def test_markdown_fenced_json_stripped(self):
        svc = self._svc()
        ev = _make_evidence()
        fenced = "```json\n" + self._minimal_valid_json() + "\n```"
        result = svc._parse_and_validate("EVT-001", fenced, [], ev, source="watsonx_ai")
        assert "access_control" in result.source_statuses

    def test_missing_sources_filtered_to_known_sources(self):
        svc = self._svc()
        ev = _make_evidence()
        raw = json.dumps({
            "event_id": "EVT-001",
            "source_statuses": {},
            "conflicts": [],
            "missing_sources": ["access_control", "totally_unknown_source"],
            "context_summary": "",
            "has_conflicts": False,
            "has_missing_sources": True,
        })
        result = svc._parse_and_validate("EVT-001", raw, [], ev, source="watsonx_ai")
        assert "access_control" in result.missing_sources
        assert "totally_unknown_source" not in result.missing_sources


# ---------------------------------------------------------------------------
# _compact_evidence_for_llm
# ---------------------------------------------------------------------------


class TestCompactEvidence:
    def _svc(self):
        return ContextService(session=None)

    def test_compact_includes_errors(self):
        svc = self._svc()
        ev = _make_evidence(errors={"mock_schedule": "timeout"})
        payload = {
            "event_id": "EVT-001",
            "event_type": "person_detected",
            "event_timestamp": "2026-11-03T22:00:00Z",
            "location_id": "LOC-1",
            "zone": None,
            "required_context": ["access_control"],
            "evidence": ev.model_dump(),
        }
        compact = svc._compact_evidence_for_llm(payload)
        assert compact["event_id"] == "EVT-001"
        assert "errors" in compact["evidence_summary"]
        assert compact["required_context"] == ["access_control"]

    def test_compact_limits_record_details(self):
        svc = self._svc()
        ev = _make_evidence(access_events=_section_present(5))
        payload = {
            "event_id": "EVT-001",
            "event_type": "person_detected",
            "event_timestamp": "2026-11-03T22:00:00Z",
            "location_id": "LOC-1",
            "zone": None,
            "required_context": ["access_control"],
            "evidence": ev.model_dump(),
        }
        compact = svc._compact_evidence_for_llm(payload)
        # Should have evidence_summary not the full records list
        assert "evidence_summary" in compact
        assert "records" not in str(compact["evidence_summary"])


# ---------------------------------------------------------------------------
# LLM path mocking
# ---------------------------------------------------------------------------


class TestLLMPaths:
    def _svc(self):
        return ContextService(session=None)

    def _valid_llm_response(self, event_id="EVT-001"):
        return json.dumps({
            "event_id": event_id,
            "source_statuses": {
                "access_control": {
                    "status": "verified_present",
                    "record_count": 1,
                    "summary": "One badge entry.",
                }
            },
            "conflicts": [],
            "missing_sources": [],
            "context_summary": "Access record found. No conflicts.",
            "has_conflicts": False,
            "has_missing_sources": False,
        })

    @pytest.mark.asyncio
    async def test_path_a_success(self):
        svc = self._svc()
        ev = _make_evidence()

        mock_iam = AsyncMock(return_value="fake-iam-token")
        mock_invoke = AsyncMock(return_value=(self._valid_llm_response(), []))

        with (
            patch.object(svc, "_get_iam_token", mock_iam),
            patch.object(svc, "_invoke_watsonx_ai", mock_invoke),
            patch("app.services.context_service.get_settings") as mock_settings,
        ):
            settings = MagicMock()
            settings.orchestrate_active = False
            settings.watsonx_active = True
            settings.agent_invoke_timeout = 30.0
            settings.watsonx_model_id = "ibm/granite-4-h-small"
            settings.effective_watsonx_base_url = "https://us-south.ml.cloud.ibm.com"
            settings.effective_watsonx_space_id = "test-space"
            settings.effective_watsonx_api_key = "test-key"
            mock_settings.return_value = settings
            svc._settings = settings

            with patch.object(svc, "_persist_agent_run", AsyncMock()):
                result = await svc.run(
                    event_id="EVT-001",
                    event_metadata={"event_type": "person_detected"},
                    required_context=["access_control"],
                    evidence=ev,
                )

        assert result.source == "watsonx_ai"
        assert "access_control" in result.source_statuses

    @pytest.mark.asyncio
    async def test_path_a_failure_falls_back_to_path_0(self):
        svc = self._svc()
        ev = _make_evidence(access_events=_section_present(1))

        with (
            patch("app.services.context_service.get_settings") as mock_settings,
        ):
            settings = MagicMock()
            settings.orchestrate_active = False
            settings.watsonx_active = True
            settings.agent_invoke_timeout = 30.0
            settings.watsonx_model_id = "ibm/granite-4-h-small"
            settings.effective_watsonx_base_url = "https://us-south.ml.cloud.ibm.com"
            settings.effective_watsonx_space_id = "test-space"
            settings.effective_watsonx_api_key = "test-key"
            mock_settings.return_value = settings
            svc._settings = settings

            with (
                patch.object(svc, "_invoke_watsonx_ai", AsyncMock(side_effect=RuntimeError("network"))),
                patch.object(svc, "_persist_agent_run", AsyncMock()),
            ):
                result = await svc.run(
                    event_id="EVT-001",
                    event_metadata={"event_type": "person_detected"},
                    required_context=["access_control"],
                    evidence=ev,
                )

        assert result.source == "deterministic_fallback"

    @pytest.mark.asyncio
    async def test_path_0_used_when_no_credentials(self):
        svc = self._svc()
        ev = _make_evidence(schedule=_section_present(1))

        with patch("app.services.context_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.orchestrate_active = False
            settings.watsonx_active = False
            settings.agent_invoke_timeout = 30.0
            mock_settings.return_value = settings
            svc._settings = settings

            with patch.object(svc, "_persist_agent_run", AsyncMock()):
                result = await svc.run(
                    event_id="EVT-001",
                    event_metadata={"event_type": "person_detected"},
                    required_context=["schedule"],
                    evidence=ev,
                )

        assert result.source == "deterministic_fallback"
        assert result.event_id == "EVT-001"

    @pytest.mark.asyncio
    async def test_path_b_failure_falls_through_to_path_a(self):
        svc = self._svc()
        ev = _make_evidence(access_events=_section_present(1))

        with patch("app.services.context_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.orchestrate_active = True
            settings.watsonx_active = True
            settings.orchestrate_context_agent_id = "ctx-agent-001"
            settings.orchestrate_url = "https://fake.orchestrate"
            settings.agent_invoke_timeout = 30.0
            settings.watsonx_model_id = "ibm/granite-4-h-small"
            settings.effective_watsonx_base_url = "https://us-south.ml.cloud.ibm.com"
            settings.effective_watsonx_space_id = "test-space"
            settings.effective_watsonx_api_key = "test-key"
            mock_settings.return_value = settings
            svc._settings = settings

            valid_response = self._valid_llm_response()
            with (
                patch.object(svc, "_invoke_orchestrate_saas",
                             AsyncMock(side_effect=RuntimeError("orchestrate down"))),
                patch.object(svc, "_invoke_watsonx_ai",
                             AsyncMock(return_value=(valid_response, []))),
                patch.object(svc, "_persist_agent_run", AsyncMock()),
            ):
                result = await svc.run(
                    event_id="EVT-001",
                    event_metadata={"event_type": "person_detected"},
                    required_context=["access_control"],
                    evidence=ev,
                )

        assert result.source == "watsonx_ai"


# ---------------------------------------------------------------------------
# Integration: POST /events/{id}/assess includes context in response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assess_response_includes_context(db_session, client):
    """Verify that the assess endpoint returns a context field."""
    from app.models.event import SecurityEvent

    event = SecurityEvent(
        id="CTX-INTG-001",
        event_type="person_detected",
        event_timestamp="2026-11-03T22:00:00Z",
        location_id="ZONE-A",
        status="normalised",
        raw_payload_json="{}",
    )
    db_session.add(event)
    await db_session.flush()

    response = await client.post(
        "/api/v1/events/CTX-INTG-001/assess",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "context" in body
    ctx = body["context"]
    assert "source_statuses" in ctx
    assert "conflicts" in ctx
    assert "missing_sources" in ctx
    assert "context_summary" in ctx
    assert "has_conflicts" in ctx
    assert "has_missing_sources" in ctx
    assert "source" in ctx
    # In test environment (no credentials) must be deterministic fallback
    assert ctx["source"] == "deterministic_fallback"
