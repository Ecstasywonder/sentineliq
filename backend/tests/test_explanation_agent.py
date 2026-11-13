"""
Master Build Prompt Gate 13 — Explanation Service tests.

Tests cover:
1. Deterministic fallback (no LLM credentials configured)
   - summary construction from event_type + location + risk_level
   - why list built from triggered risk factors only
   - missing_evidence from evidence_errors
   - limitations from low confidence and conflicts
   - recommended_action from risk_level
2. LLM path (mocked HTTP)
   - Path B success
   - Path B failure → Path 0 fallback
   - No credentials → Path 0
3. Agent output validation / injection filtering
   - risk_score / risk_level echoed from deterministic input, not agent
   - forbidden words replaced in summary and why text
   - summary truncated at 512 chars
   - recommended_action truncated at 512 chars
   - why items with empty text discarded
   - non-JSON output → fallback (ValueError raised)
   - markdown-fenced JSON stripped
4. missing_evidence includes evidence_errors sources
5. Integration: POST /events/{id}/assess includes explanation in response
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.explanation_service import ExplanationService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event_meta(
    event_type: str = "person_detected",
    location_id: str = "LOADING_DOCK_3",
    zone: str | None = None,
    timestamp: str = "2026-11-03T22:00:00Z",
) -> dict:
    return {
        "event_type": event_type,
        "event_timestamp": timestamp,
        "location_id": location_id,
        "facility_id": "FAC-001",
        "zone": zone,
    }


def _triggered_factors(ids: list[str]) -> list[dict]:
    labels = {
        "after_hours_access": "After-hours access detected",
        "unverified_person": "Unverified person",
        "no_work_order": "No work order",
        "no_scheduled_entry": "No scheduled entry",
        "known_incident_area": "Known incident area",
        "critical_zone": "Critical zone",
    }
    factors = []
    for fid in ids:
        factors.append(
            {
                "factor_id": fid,
                "label": labels.get(fid, fid),
                "triggered": True,
                "contribution": 0.15,
            }
        )
    return factors


def _all_factors_not_triggered() -> list[dict]:
    return [
        {
            "factor_id": "after_hours_access",
            "label": "After-hours",
            "triggered": False,
            "contribution": 0.0,
        },
        {"factor_id": "no_work_order", "label": "No WO", "triggered": False, "contribution": 0.0},
    ]


def _make_context(missing: list[str] | None = None, has_conflicts: bool = False):
    ctx = MagicMock()
    ctx.missing_sources = missing or []
    ctx.has_conflicts = has_conflicts
    ctx.model_dump.return_value = {
        "missing_sources": missing or [],
        "has_conflicts": has_conflicts,
        "context_summary": "Evidence assessed.",
        "source_statuses": {},
        "conflicts": [],
    }
    return ctx


def _valid_llm_response(event_id: str = "EVT-001") -> str:
    return json.dumps(
        {
            "event_id": event_id,
            "summary": "Unverified activity was detected at the loading dock after hours.",
            "risk_level": "high",
            "risk_score": 0.72,
            "confidence_score": 0.88,
            "why": [
                {
                    "text": "No authorised badge event was found within the time window.",
                    "evidence_ids": ["ACCESS-Q-221"],
                }
            ],
            "missing_evidence": [],
            "limitations": [],
            "recommended_action": "Review the live camera feed and verify with the shift supervisor.",
            "has_missing_evidence": False,
            "has_limitations": False,
        }
    )


_VALID_EVIDENCE_IDS = {"ACCESS-Q-221", "mock_access_control", "mock_schedule"}


# ---------------------------------------------------------------------------
# Unit tests — deterministic fallback
# ---------------------------------------------------------------------------


class TestDeterministicFallback:
    def _svc(self) -> ExplanationService:
        return ExplanationService(session=None)

    def test_evidence_references_include_only_valid_record_ids(self):
        svc = self._svc()
        evidence = {
            "access_events": {
                "meta": {"source": "mock_access_control"},
                "records": [{"id": "ACCESS-Q-221"}, {"description": "no id"}],
            },
            "schedule": None,
        }

        assert svc._build_evidence_references(evidence) == [
            {
                "source_id": "mock_access_control",
                "record_ids": ["ACCESS-Q-221"],
            }
        ]

    def test_summary_contains_event_type_and_location(self):
        svc = self._svc()
        result = svc._deterministic_explanation(
            event_id="EVT-001",
            event_metadata=_make_event_meta(event_type="door_forced", location_id="ZONE-B"),
            risk_score=0.8,
            risk_level="high",
            risk_factors=_triggered_factors(["after_hours_access"]),
            confidence_score=0.9,
            context_result=None,
            evidence_errors={},
        )
        assert "door_forced" in result.summary
        assert "ZONE-B" in result.summary
        assert "high" in result.summary

    def test_summary_includes_zone(self):
        svc = self._svc()
        result = svc._deterministic_explanation(
            event_id="EVT-001",
            event_metadata=_make_event_meta(zone="restricted_area"),
            risk_score=0.7,
            risk_level="high",
            risk_factors=[],
            confidence_score=0.85,
            context_result=None,
            evidence_errors={},
        )
        assert "restricted_area" in result.summary

    def test_why_list_built_from_triggered_factors_only(self):
        svc = self._svc()
        factors = [
            {
                "factor_id": "after_hours_access",
                "label": "After hours",
                "triggered": True,
                "contribution": 0.2,
            },
            {
                "factor_id": "no_work_order",
                "label": "No WO",
                "triggered": False,
                "contribution": 0.0,
            },
        ]
        result = svc._deterministic_explanation(
            event_id="EVT-001",
            event_metadata=_make_event_meta(),
            risk_score=0.5,
            risk_level="medium",
            risk_factors=factors,
            confidence_score=0.85,
            context_result=None,
            evidence_errors={},
            evidence_references=[
                {
                    "source_id": "mock_access_control",
                    "record_ids": ["ACCESS-Q-221"],
                }
            ],
        )
        assert len(result.why) == 1
        assert result.why[0].evidence_ids == ["ACCESS-Q-221"]

    def test_no_triggered_factors_no_why(self):
        svc = self._svc()
        result = svc._deterministic_explanation(
            event_id="EVT-001",
            event_metadata=_make_event_meta(),
            risk_score=0.1,
            risk_level="low",
            risk_factors=_all_factors_not_triggered(),
            confidence_score=0.95,
            context_result=None,
            evidence_errors={},
        )
        assert result.why == []

    def test_missing_evidence_from_evidence_errors(self):
        svc = self._svc()
        result = svc._deterministic_explanation(
            event_id="EVT-001",
            event_metadata=_make_event_meta(),
            risk_score=0.5,
            risk_level="medium",
            risk_factors=[],
            confidence_score=0.7,
            context_result=None,
            evidence_errors={"mock_schedule": "timeout", "mock_access_control": "error"},
        )
        assert result.has_missing_evidence
        # Both sources should appear
        assert any("mock_schedule" in m for m in result.missing_evidence)
        assert any("mock_access_control" in m for m in result.missing_evidence)

    def test_missing_evidence_from_context_missing_sources(self):
        svc = self._svc()
        ctx = _make_context(missing=["access_control", "schedule"])
        result = svc._deterministic_explanation(
            event_id="EVT-001",
            event_metadata=_make_event_meta(),
            risk_score=0.5,
            risk_level="medium",
            risk_factors=[],
            confidence_score=0.7,
            context_result=ctx,
            evidence_errors={},
        )
        assert result.has_missing_evidence
        assert any("access_control" in m for m in result.missing_evidence)

    def test_limitation_added_for_low_confidence(self):
        svc = self._svc()
        result = svc._deterministic_explanation(
            event_id="EVT-001",
            event_metadata=_make_event_meta(),
            risk_score=0.5,
            risk_level="medium",
            risk_factors=[],
            confidence_score=0.45,  # below 0.6 threshold
            context_result=None,
            evidence_errors={},
        )
        assert result.has_limitations
        assert any("limits the reliability" in lt.lower() for lt in result.limitations)

    def test_no_limitation_for_high_confidence(self):
        svc = self._svc()
        result = svc._deterministic_explanation(
            event_id="EVT-001",
            event_metadata=_make_event_meta(),
            risk_score=0.5,
            risk_level="medium",
            risk_factors=[],
            confidence_score=0.92,
            context_result=None,
            evidence_errors={},
        )
        assert not result.has_limitations

    def test_limitation_added_for_conflicts(self):
        svc = self._svc()
        ctx = _make_context(has_conflicts=True)
        result = svc._deterministic_explanation(
            event_id="EVT-001",
            event_metadata=_make_event_meta(),
            risk_score=0.6,
            risk_level="high",
            risk_factors=[],
            confidence_score=0.8,
            context_result=ctx,
            evidence_errors={},
        )
        assert result.has_limitations
        assert any("conflict" in lt.lower() for lt in result.limitations)

    def test_recommended_action_varies_by_risk_level(self):
        svc = self._svc()
        for level, expected_word in [
            ("critical", "Escalate"),
            ("high", "Review"),
            ("medium", "Verify"),
            ("low", "Log"),
        ]:
            result = svc._deterministic_explanation(
                event_id="EVT-001",
                event_metadata=_make_event_meta(),
                risk_score=0.5,
                risk_level=level,
                risk_factors=[],
                confidence_score=0.85,
                context_result=None,
                evidence_errors={},
            )
            assert expected_word in result.recommended_action, (
                f"Expected '{expected_word}' in action for level='{level}'"
            )

    def test_source_is_deterministic_fallback(self):
        svc = self._svc()
        result = svc._deterministic_explanation(
            event_id="EVT-001",
            event_metadata=_make_event_meta(),
            risk_score=0.5,
            risk_level="medium",
            risk_factors=[],
            confidence_score=0.85,
            context_result=None,
            evidence_errors={},
        )
        assert result.source == "deterministic_fallback"

    def test_summary_truncated_at_512(self):
        svc = self._svc()
        result = svc._deterministic_explanation(
            event_id="EVT-001",
            event_metadata=_make_event_meta(location_id="X" * 600),
            risk_score=0.5,
            risk_level="medium",
            risk_factors=[],
            confidence_score=0.85,
            context_result=None,
            evidence_errors={},
        )
        assert len(result.summary) <= 512


# ---------------------------------------------------------------------------
# Agent output validation / injection filtering
# ---------------------------------------------------------------------------


class TestParseAndValidate:
    def _svc(self) -> ExplanationService:
        return ExplanationService(session=None)

    def test_valid_json_parses_correctly(self):
        svc = self._svc()
        result = svc._parse_and_validate(
            "EVT-001",
            _valid_llm_response(),
            0.72,
            "high",
            0.88,
            {},
            source="orchestrate",
            valid_evidence_ids=_VALID_EVIDENCE_IDS,
        )
        assert result.source == "orchestrate"
        assert result.risk_level == "high"
        assert result.risk_score == 0.72  # echoed from arg, not agent output
        assert result.confidence_score == 0.88
        assert len(result.why) == 1

    def test_incomplete_object_is_rejected(self):
        svc = self._svc()
        with pytest.raises(ValueError, match="violated its contract"):
            svc._parse_and_validate("EVT-001", "{}", 0.5, "medium", 0.8, {}, source="orchestrate")

    def test_mismatched_boolean_flags_are_rejected(self):
        svc = self._svc()
        payload = json.loads(_valid_llm_response())
        payload["missing_evidence"] = ["schedule unavailable"]
        with pytest.raises(ValueError, match="has_missing_evidence"):
            svc._parse_and_validate(
                "EVT-001",
                json.dumps(payload),
                0.72,
                "high",
                0.88,
                {},
                source="orchestrate",
            )

    def test_risk_score_echoed_from_deterministic_not_agent(self):
        """Agent may return a different risk_score — we must ignore it."""
        svc = self._svc()
        agent_raw = json.dumps(
            {
                "event_id": "EVT-001",
                "summary": "Test.",
                "risk_level": "low",  # agent says low
                "risk_score": 0.1,  # agent says 0.1
                "confidence_score": 0.5,
                "why": [],
                "missing_evidence": [],
                "limitations": [],
                "recommended_action": "Monitor.",
                "has_missing_evidence": False,
                "has_limitations": False,
            }
        )
        result = svc._parse_and_validate(
            "EVT-001",
            agent_raw,
            0.85,
            "critical",  # deterministic says critical / 0.85
            0.90,
            {},
            source="orchestrate",
        )
        # Must always echo the deterministic values
        assert result.risk_score == 0.85
        assert result.risk_level == "critical"
        assert result.confidence_score == 0.90

    def test_risk_score_contract_uses_engine_zero_to_two_hundred_scale(self):
        svc = self._svc()
        payload = json.loads(_valid_llm_response())
        payload["risk_score"] = 78.0
        result = svc._parse_and_validate(
            "EVT-001",
            json.dumps(payload),
            78.0,
            "critical",
            0.90,
            {},
            source="orchestrate",
            valid_evidence_ids=_VALID_EVIDENCE_IDS,
        )
        assert result.risk_score == 78.0

    def test_forbidden_words_replaced_in_summary(self):
        svc = self._svc()
        raw = json.dumps(
            {
                "event_id": "EVT-001",
                "summary": "A criminal was detected at the entrance.",
                "risk_level": "high",
                "risk_score": 0.7,
                "confidence_score": 0.8,
                "why": [],
                "missing_evidence": [],
                "limitations": [],
                "recommended_action": "Review.",
                "has_missing_evidence": False,
                "has_limitations": False,
            }
        )
        result = svc._parse_and_validate("EVT-001", raw, 0.7, "high", 0.8, {}, source="orchestrate")
        assert "criminal" not in result.summary.lower()
        assert "individual" in result.summary.lower()

    def test_forbidden_words_replaced_in_why_text(self):
        svc = self._svc()
        raw = json.dumps(
            {
                "event_id": "EVT-001",
                "summary": "Test.",
                "risk_level": "high",
                "risk_score": 0.7,
                "confidence_score": 0.8,
                "why": [{"text": "An intruder was found.", "evidence_ids": ["ACCESS-Q-221"]}],
                "missing_evidence": [],
                "limitations": [],
                "recommended_action": "Review.",
                "has_missing_evidence": False,
                "has_limitations": False,
            }
        )
        result = svc._parse_and_validate(
            "EVT-001",
            raw,
            0.7,
            "high",
            0.8,
            {},
            source="orchestrate",
            valid_evidence_ids=_VALID_EVIDENCE_IDS,
        )
        assert "intruder" not in result.why[0].text.lower()

    def test_unknown_evidence_citations_are_discarded(self):
        svc = self._svc()
        raw = json.dumps(
            {
                "event_id": "EVT-001",
                "summary": "Test.",
                "risk_level": "high",
                "risk_score": 0.7,
                "confidence_score": 0.8,
                "why": [
                    {"text": "Unsupported claim.", "evidence_ids": ["invented-id"]},
                    {"text": "Supported claim.", "evidence_ids": ["ACCESS-Q-221"]},
                ],
                "missing_evidence": [],
                "limitations": [],
                "recommended_action": "Review.",
                "has_missing_evidence": False,
                "has_limitations": False,
            }
        )

        result = svc._parse_and_validate(
            "EVT-001",
            raw,
            0.7,
            "high",
            0.8,
            {},
            source="orchestrate",
            valid_evidence_ids=_VALID_EVIDENCE_IDS,
        )

        assert [reason.text for reason in result.why] == ["Supported claim."]
        assert result.why[0].evidence_ids == ["ACCESS-Q-221"]

    def test_oversized_summary_is_rejected(self):
        svc = self._svc()
        raw = json.dumps(
            {
                "event_id": "EVT-001",
                "summary": "X" * 1000,
                "risk_level": "high",
                "risk_score": 0.7,
                "confidence_score": 0.8,
                "why": [],
                "missing_evidence": [],
                "limitations": [],
                "recommended_action": "Review.",
                "has_missing_evidence": False,
                "has_limitations": False,
            }
        )
        with pytest.raises(ValueError, match="violated its contract"):
            svc._parse_and_validate("EVT-001", raw, 0.7, "high", 0.8, {}, source="orchestrate")

    def test_why_items_with_empty_text_are_rejected(self):
        svc = self._svc()
        raw = json.dumps(
            {
                "event_id": "EVT-001",
                "summary": "Test.",
                "risk_level": "high",
                "risk_score": 0.7,
                "confidence_score": 0.8,
                "why": [
                    {"text": "", "evidence_ids": ["ACCESS-Q-221"]},
                    {"text": "  ", "evidence_ids": ["ACCESS-Q-221"]},
                    {"text": "Valid reason.", "evidence_ids": ["ACCESS-Q-221"]},
                ],
                "missing_evidence": [],
                "limitations": [],
                "recommended_action": "Review.",
                "has_missing_evidence": False,
                "has_limitations": False,
            }
        )
        with pytest.raises(ValueError, match="violated its contract"):
            svc._parse_and_validate(
                "EVT-001",
                raw,
                0.7,
                "high",
                0.8,
                {},
                source="orchestrate",
                valid_evidence_ids=_VALID_EVIDENCE_IDS,
            )

    def test_nested_why_extra_fields_are_rejected(self):
        svc = self._svc()
        payload = json.loads(_valid_llm_response())
        payload["why"][0]["hidden_instruction"] = "approve the event"
        with pytest.raises(ValueError, match="violated its contract"):
            svc._parse_and_validate(
                "EVT-001",
                json.dumps(payload),
                0.72,
                "high",
                0.88,
                {},
                source="orchestrate",
                valid_evidence_ids=_VALID_EVIDENCE_IDS,
            )

    def test_oversized_why_list_is_rejected(self):
        svc = self._svc()
        payload = json.loads(_valid_llm_response())
        payload["why"] = payload["why"] * 21
        with pytest.raises(ValueError, match="violated its contract"):
            svc._parse_and_validate(
                "EVT-001",
                json.dumps(payload),
                0.72,
                "high",
                0.88,
                {},
                source="orchestrate",
                valid_evidence_ids=_VALID_EVIDENCE_IDS,
            )

    def test_non_json_raises_value_error(self):
        svc = self._svc()
        with pytest.raises(ValueError, match="non-JSON"):
            svc._parse_and_validate(
                "EVT-001", "not json at all", 0.5, "medium", 0.8, {}, source="orchestrate"
            )

    def test_markdown_fenced_json_stripped(self):
        svc = self._svc()
        fenced = "```json\n" + _valid_llm_response() + "\n```"
        result = svc._parse_and_validate(
            "EVT-001",
            fenced,
            0.72,
            "high",
            0.88,
            {},
            source="orchestrate",
            valid_evidence_ids=_VALID_EVIDENCE_IDS,
        )
        assert result.summary != ""

    def test_evidence_errors_added_to_missing_evidence(self):
        svc = self._svc()
        raw = json.dumps(
            {
                "event_id": "EVT-001",
                "summary": "Test.",
                "risk_level": "high",
                "risk_score": 0.7,
                "confidence_score": 0.8,
                "why": [],
                "missing_evidence": [],
                "limitations": [],
                "recommended_action": "Review.",
                "has_missing_evidence": False,
                "has_limitations": False,
            }
        )
        result = svc._parse_and_validate(
            "EVT-001",
            raw,
            0.7,
            "high",
            0.8,
            {"mock_schedule": "timeout"},
            source="orchestrate",
            known_missing_sources=["schedule"],
        )
        assert result.has_missing_evidence
        assert any("mock_schedule" in m for m in result.missing_evidence)
        assert "schedule status unavailable" in result.missing_evidence

    def test_enforcement_recommendation_is_rejected(self):
        svc = self._svc()
        raw = json.dumps(
            {
                "event_id": "EVT-001",
                "summary": "Test.",
                "risk_level": "high",
                "risk_score": 0.7,
                "confidence_score": 0.8,
                "why": [],
                "missing_evidence": [],
                "limitations": [],
                "recommended_action": "Detain the person immediately.",
                "has_missing_evidence": False,
                "has_limitations": False,
            }
        )

        with pytest.raises(ValueError, match="prohibited enforcement"):
            svc._parse_and_validate("EVT-001", raw, 0.7, "high", 0.8, {}, source="orchestrate")

    def test_enforcement_in_summary_is_rejected(self):
        svc = self._svc()
        payload = json.loads(_valid_llm_response())
        payload["summary"] = "Security should contact law enforcement now."
        with pytest.raises(ValueError, match="prohibited enforcement"):
            svc._parse_and_validate(
                "EVT-001",
                json.dumps(payload),
                0.72,
                "high",
                0.88,
                {},
                source="orchestrate",
                valid_evidence_ids=_VALID_EVIDENCE_IDS,
            )

    def test_invalid_agent_risk_level_is_rejected(self):
        svc = self._svc()
        raw = json.dumps(
            {
                "event_id": "EVT-001",
                "summary": "Test.",
                "risk_level": "EXTREME",  # invalid
                "risk_score": 0.9,
                "confidence_score": 0.8,
                "why": [],
                "missing_evidence": [],
                "limitations": [],
                "recommended_action": "Review.",
                "has_missing_evidence": False,
                "has_limitations": False,
            }
        )
        with pytest.raises(ValueError, match="violated its contract"):
            svc._parse_and_validate("EVT-001", raw, 0.9, "high", 0.8, {}, source="orchestrate")


# ---------------------------------------------------------------------------
# LLM path mocking
# ---------------------------------------------------------------------------


class TestLLMPaths:
    def _svc(self) -> ExplanationService:
        return ExplanationService(session=None)

    @pytest.mark.asyncio
    async def test_failed_model_and_fallback_use_distinct_attempt_ids(self, db_session):
        from sqlalchemy import select

        from app.models.agent_run import AgentRun
        from app.models.event import SecurityEvent

        event = SecurityEvent(
            id="EXPL-ATTEMPT-001",
            event_type="person_detected",
            event_timestamp="2026-11-03T22:00:00Z",
            location_id="ZONE-A",
            status="normalised",
        )
        db_session.add(event)
        await db_session.flush()

        svc = ExplanationService(session=db_session)
        settings = MagicMock()
        settings.orchestrate_active = True
        settings.agent_invoke_timeout = 30.0
        settings.orchestrate_explanation_agent_id = "expl-agent-001"
        svc._settings = settings

        with patch.object(
            svc,
            "_invoke_orchestrate_saas",
            AsyncMock(side_effect=RuntimeError("network error")),
        ):
            result = await svc.run(
                event_id=event.id,
                event_metadata=_make_event_meta(),
                triage_result=None,
                context_result=None,
                risk_score=0.72,
                risk_level="high",
                risk_factors=[],
                confidence_score=0.88,
                confidence_level="high",
                evidence_errors={},
            )

        rows = list(
            (
                await db_session.execute(
                    select(AgentRun)
                    .where(AgentRun.event_id == event.id)
                    .where(AgentRun.agent_name == "sentinel_explanation_agent")
                )
            ).scalars()
        )
        assert len(rows) == 2
        assert len({row.id for row in rows}) == 2
        assert {row.status for row in rows} == {"failed", "failed_fallback"}
        assert result.agent_run_id in {row.id for row in rows}

    @pytest.mark.asyncio
    async def test_path_0_used_when_no_credentials(self):
        svc = self._svc()

        with patch("app.services.explanation_service.get_settings") as mock_cfg:
            settings = MagicMock()
            settings.orchestrate_active = False
            settings.agent_invoke_timeout = 30.0
            mock_cfg.return_value = settings
            svc._settings = settings

            with patch.object(svc, "_persist_agent_run", AsyncMock()):
                result = await svc.run(
                    event_id="EVT-001",
                    event_metadata=_make_event_meta(),
                    triage_result=None,
                    context_result=None,
                    risk_score=0.5,
                    risk_level="medium",
                    risk_factors=[],
                    confidence_score=0.85,
                    confidence_level="medium",
                    evidence_errors={},
                )

        assert result.source == "deterministic_fallback"
        assert result.event_id == "EVT-001"

    @pytest.mark.asyncio
    async def test_path_b_failure_falls_through_to_path_0(self):
        svc = self._svc()

        with patch("app.services.explanation_service.get_settings") as mock_cfg:
            settings = MagicMock()
            settings.orchestrate_active = True
            settings.orchestrate_explanation_agent_id = "expl-agent-001"
            settings.orchestrate_url = "https://fake.orchestrate"
            settings.agent_invoke_timeout = 30.0
            settings.effective_watsonx_base_url = "https://us-south.ml.cloud.ibm.com"
            settings.effective_watsonx_api_key = "legacy-key"
            settings.effective_watsonx_space_id = "legacy-space"
            mock_cfg.return_value = settings
            svc._settings = settings
            assert not hasattr(svc, "_invoke_watsonx_ai")

            with (
                patch.object(
                    svc,
                    "_invoke_orchestrate_saas",
                    AsyncMock(side_effect=RuntimeError("orchestrate down")),
                ),
                patch.object(svc, "_persist_agent_run", AsyncMock()) as persist_run,
                patch("httpx.AsyncClient.post", new_callable=AsyncMock) as direct_chat_post,
            ):
                result = await svc.run(
                    event_id="EVT-001",
                    event_metadata=_make_event_meta(),
                    triage_result=None,
                    context_result=None,
                    risk_score=0.72,
                    risk_level="high",
                    risk_factors=_triggered_factors(["after_hours_access"]),
                    confidence_score=0.88,
                    confidence_level="high",
                    evidence_errors={},
                )

        assert result.source == "deterministic_fallback"
        direct_chat_post.assert_not_awaited()
        assert persist_run.await_count == 2
        failed_remote, safe_fallback = [call.kwargs for call in persist_run.await_args_list]
        assert failed_remote["status"] == "failed"
        assert failed_remote["path"] == "orchestrate"
        assert safe_fallback["status"] == "failed_fallback"
        assert safe_fallback["path"] == "deterministic"


# ---------------------------------------------------------------------------
# Integration: POST /events/{id}/assess includes explanation in response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assess_response_includes_explanation(db_session, client):
    """Verify that the assess endpoint returns an explanation field."""
    from app.models.event import SecurityEvent

    event = SecurityEvent(
        id="EXPL-INTG-001",
        event_type="person_detected",
        event_timestamp="2026-11-03T22:00:00Z",
        location_id="ZONE-A",
        status="normalised",
    )
    db_session.add(event)
    await db_session.flush()

    response = await client.post(
        "/api/v1/events/EXPL-INTG-001/assess",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    body = response.json()

    assert "explanation" in body
    expl = body["explanation"]

    # Required fields
    assert "summary" in expl
    assert "risk_level" in expl
    assert "risk_score" in expl
    assert "confidence_score" in expl
    assert "why" in expl
    assert "missing_evidence" in expl
    assert "limitations" in expl
    assert "recommended_action" in expl
    assert "has_missing_evidence" in expl
    assert "has_limitations" in expl
    assert "source" in expl
    assert "agent_run_id" in expl

    # In test environment (no credentials) must be deterministic fallback
    assert expl["source"] == "deterministic_fallback"

    # Risk level and score must match the top-level values
    assert expl["risk_level"] == body["risk_level"]
    assert abs(expl["risk_score"] - body["risk_score"]) < 0.001

    # recommended_action must not contain enforcement language
    action = expl["recommended_action"].lower()
    for forbidden in ("detain", "arrest", "lock down", "ban"):
        assert forbidden not in action, f"Forbidden word '{forbidden}' in recommended_action"


@pytest.mark.asyncio
async def test_assessment_bundle_tool_reconstructs_persisted_run(db_session, client):
    from app.models.event import SecurityEvent

    event = SecurityEvent(
        id="EXPL-BUNDLE-001",
        event_type="door_forced",
        event_timestamp="2026-11-03T23:00:00Z",
        location_id="ZONE-BUNDLE",
        status="normalised",
    )
    db_session.add(event)
    await db_session.flush()

    assessed = await client.post("/api/v1/events/EXPL-BUNDLE-001/assess", json={})
    assert assessed.status_code == 200

    response = await client.get(
        "/api/v1/tools/assessment-bundle",
        params={"event_id": "EXPL-BUNDLE-001"},
    )
    assert response.status_code == 200
    bundle = response.json()
    assert bundle["event_id"] == "EXPL-BUNDLE-001"
    assert bundle["triage"]["event_id"] == "EXPL-BUNDLE-001"
    assert bundle["context"]["event_id"] == "EXPL-BUNDLE-001"
    assert bundle["explanation"]["event_id"] == "EXPL-BUNDLE-001"
    assert bundle["recommendation_id"]
    assert bundle["recommendation"]["id"] == bundle["recommendation_id"]
    assert bundle["recommendation"]["recommended_action"]
    assert bundle["recommendation"]["requires_human_review"] is True
    assert bundle["workflow_state"]["event_status"]["after"] == "awaiting_review"
    assert bundle["workflow_state"]["human_review_required"] is True
