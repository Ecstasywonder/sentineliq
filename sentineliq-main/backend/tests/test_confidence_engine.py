"""
Confidence Engine tests — Gate 4.

Tests cover:
- Perfect score (all sources available, no reductions)
- Each reduction type individually
- Multiple reductions stacked
- Score floor clamp at 0.0
- Score ceiling clamp at 1.0 (score can never exceed 1.0)
- Level classification boundaries (high/medium/low)
- Optional sources do NOT reduce confidence when unavailable
- Tool retrieval errors vs clean source unavailability are separate reductions
- reductions_json round-trip
- ADR-004: Confidence Engine requires no DB session (pure Python)
- Custom reduction_amounts override
"""

from __future__ import annotations

import json

import pytest

from app.services.confidence_engine import (
    ConfidenceEngine,
    ConfidenceReduction,
    ConfidenceResult,
    SourceStatus,
    _classify_confidence,
)

# ---------------------------------------------------------------------------
# _classify_confidence unit tests (pure, no DB, no async)
# ---------------------------------------------------------------------------

class TestClassifyConfidence:
    def test_score_1_0_is_high(self):
        assert _classify_confidence(1.0) == "high"

    def test_score_0_8_is_high(self):
        assert _classify_confidence(0.80) == "high"

    def test_score_0_79_is_medium(self):
        assert _classify_confidence(0.79) == "medium"

    def test_score_0_5_is_medium(self):
        assert _classify_confidence(0.50) == "medium"

    def test_score_0_49_is_low(self):
        assert _classify_confidence(0.49) == "low"

    def test_score_0_0_is_low(self):
        assert _classify_confidence(0.0) == "low"


# ---------------------------------------------------------------------------
# ConfidenceEngine tests (synchronous — no DB needed, ADR-004)
# ---------------------------------------------------------------------------

def _all_available(source_ids: list[str], required: bool = True) -> list[SourceStatus]:
    return [SourceStatus(source_id=s, available=True, required=required) for s in source_ids]


def _all_unavailable(source_ids: list[str], required: bool = True) -> list[SourceStatus]:
    return [SourceStatus(source_id=s, available=False, required=required) for s in source_ids]


class TestConfidenceEngineBaseline:
    def test_perfect_score_no_reductions(self):
        """All sources available, no issues → score 1.0, level high."""
        engine = ConfidenceEngine()
        sources = _all_available(["access_control", "schedule", "policy"])
        result = engine.assess(sources)

        assert result.confidence_score == 1.0
        assert result.confidence_level == "high"
        assert result.reductions == []
        assert result.sources_available == 3
        assert result.sources_required == 3

    def test_no_sources_no_reductions(self):
        """Zero sources with no other flags → perfect score."""
        engine = ConfidenceEngine()
        result = engine.assess(sources=[])
        assert result.confidence_score == 1.0
        assert result.confidence_level == "high"

    def test_result_is_confidence_result_instance(self):
        engine = ConfidenceEngine()
        result = engine.assess(sources=[])
        assert isinstance(result, ConfidenceResult)


class TestSourceUnavailableReduction:
    def test_one_unavailable_required_source(self):
        """One missing required source -> -0.20."""
        engine = ConfidenceEngine()
        sources = [SourceStatus("access_control", available=False, required=True)]
        result = engine.assess(sources)

        assert result.confidence_score == pytest.approx(0.80)
        assert result.confidence_level == "high"
        assert len(result.reductions) == 1
        assert result.reductions[0].reason == ConfidenceReduction.SOURCE_UNAVAILABLE.value
        assert result.reductions[0].source_id == "access_control"

    def test_two_unavailable_required_sources(self):
        """Two missing required sources -> -0.40 -> 0.60 (medium)."""
        engine = ConfidenceEngine()
        sources = _all_unavailable(["access_control", "schedule"])
        result = engine.assess(sources)

        assert result.confidence_score == pytest.approx(0.60)
        assert result.confidence_level == "medium"
        assert len(result.reductions) == 2

    def test_unavailable_optional_source_does_not_reduce(self):
        """Optional unavailable sources must NOT reduce confidence."""
        engine = ConfidenceEngine()
        sources = [SourceStatus("visitor", available=False, required=False)]
        result = engine.assess(sources)

        assert result.confidence_score == 1.0
        assert result.reductions == []

    def test_five_unavailable_required_clamps_to_zero(self):
        """5 x 0.20 = 1.0 reduction -> score clamped to 0.0, not negative."""
        engine = ConfidenceEngine()
        sources = _all_unavailable(["a", "b", "c", "d", "e"])
        result = engine.assess(sources)

        assert result.confidence_score == 0.0
        assert result.confidence_level == "low"


class TestStaleSourceReduction:
    def test_one_stale_source(self):
        """One stale available source -> -0.10."""
        engine = ConfidenceEngine()
        sources = [SourceStatus("access_control", available=True, stale=True)]
        result = engine.assess(sources)

        assert result.confidence_score == pytest.approx(0.90)
        assert result.confidence_level == "high"
        assert result.reductions[0].reason == ConfidenceReduction.SOURCE_STALE.value

    def test_unavailable_stale_does_not_double_reduce(self):
        """
        A source that is both unavailable AND stale should only trigger the
        'source_unavailable' reduction, not also 'source_stale'.
        (Stale reduction only applies when available=True.)
        """
        engine = ConfidenceEngine()
        sources = [SourceStatus("access_control", available=False, stale=True, required=True)]
        result = engine.assess(sources)

        reasons = [r.reason for r in result.reductions]
        assert ConfidenceReduction.SOURCE_UNAVAILABLE.value in reasons
        assert ConfidenceReduction.SOURCE_STALE.value not in reasons


class TestContradictoryEvidenceReduction:
    def test_contradictory_reduces_by_0_15(self):
        engine = ConfidenceEngine()
        result = engine.assess(sources=[], has_contradictory_evidence=True)

        assert result.confidence_score == pytest.approx(0.85)
        assert result.confidence_level == "high"
        assert result.reductions[0].reason == ConfidenceReduction.CONTRADICTORY_EVIDENCE.value


class TestIncompleteMetadataReduction:
    def test_incomplete_metadata_reduces_by_0_10(self):
        engine = ConfidenceEngine()
        result = engine.assess(sources=[], incomplete_event_metadata=True)

        assert result.confidence_score == pytest.approx(0.90)
        assert result.reductions[0].reason == ConfidenceReduction.INCOMPLETE_EVENT_METADATA.value


class TestToolRetrievalErrorReduction:
    def test_one_tool_error(self):
        """Tool retrieval error -> -0.10 per erroring source."""
        engine = ConfidenceEngine()
        result = engine.assess(sources=[], tool_retrieval_errors=["access_control"])

        assert result.confidence_score == pytest.approx(0.90)
        assert result.reductions[0].reason == ConfidenceReduction.TOOL_RETRIEVAL_ERROR.value
        assert result.reductions[0].source_id == "access_control"

    def test_tool_error_and_unavailable_are_independent(self):
        """
        A source marked unavailable AND also in tool_retrieval_errors should
        produce TWO separate reductions — they represent different failure modes.
        """
        engine = ConfidenceEngine()
        sources = [SourceStatus("schedule", available=False, required=True)]
        result = engine.assess(sources, tool_retrieval_errors=["schedule"])

        reasons = [r.reason for r in result.reductions]
        assert ConfidenceReduction.SOURCE_UNAVAILABLE.value in reasons
        assert ConfidenceReduction.TOOL_RETRIEVAL_ERROR.value in reasons
        assert result.confidence_score == pytest.approx(0.70)

    def test_tool_errors_are_deterministically_ordered(self):
        """Tool errors must appear in sorted source_id order for audit reproducibility."""
        engine = ConfidenceEngine()
        result = engine.assess(sources=[], tool_retrieval_errors=["zzz_source", "aaa_source"])

        error_reductions = [
            r for r in result.reductions
            if r.reason == ConfidenceReduction.TOOL_RETRIEVAL_ERROR.value
        ]
        source_ids = [r.source_id for r in error_reductions]
        assert source_ids == sorted(source_ids)


class TestLlmUnavailableReduction:
    def test_llm_unavailable_reduces_by_0_20(self):
        engine = ConfidenceEngine()
        result = engine.assess(sources=[], llm_unavailable=True)

        assert result.confidence_score == pytest.approx(0.80)
        assert result.confidence_level == "high"
        assert result.reductions[0].reason == ConfidenceReduction.LLM_UNAVAILABLE.value


class TestStackedReductions:
    def test_unavailable_plus_llm_unavailable(self):
        """One missing source (-0.20) + LLM unavailable (-0.20) = 0.60 (medium)."""
        engine = ConfidenceEngine()
        sources = [SourceStatus("access_control", available=False, required=True)]
        result = engine.assess(sources, llm_unavailable=True)

        assert result.confidence_score == pytest.approx(0.60)
        assert result.confidence_level == "medium"
        assert len(result.reductions) == 2

    def test_all_reductions_fires(self):
        """
        All six reduction types applied simultaneously.
        1.0 - 0.20 (unavail) - 0.10 (stale) - 0.15 (contradictory)
            - 0.10 (metadata) - 0.10 (tool error) - 0.20 (llm) = 0.15
        """
        engine = ConfidenceEngine()
        sources = [
            SourceStatus("access_control", available=False, required=True),
            SourceStatus("schedule", available=True, stale=True),
        ]
        result = engine.assess(
            sources,
            has_contradictory_evidence=True,
            incomplete_event_metadata=True,
            tool_retrieval_errors=["work_orders"],
            llm_unavailable=True,
        )

        assert result.confidence_score == pytest.approx(0.15)
        assert result.confidence_level == "low"
        assert len(result.reductions) == 6

    def test_excessive_reductions_clamp_to_zero(self):
        """Score must never go below 0.0 even with many stacked reductions."""
        engine = ConfidenceEngine()
        sources = _all_unavailable(["a", "b", "c", "d", "e"])
        result = engine.assess(
            sources,
            has_contradictory_evidence=True,
            incomplete_event_metadata=True,
            llm_unavailable=True,
        )
        assert result.confidence_score == 0.0
        assert result.confidence_score >= 0.0


class TestSourceCounts:
    def test_sources_available_count(self):
        engine = ConfidenceEngine()
        sources = [
            SourceStatus("a", available=True),
            SourceStatus("b", available=True),
            SourceStatus("c", available=False),
        ]
        result = engine.assess(sources)
        assert result.sources_available == 2

    def test_sources_required_count_excludes_optional(self):
        engine = ConfidenceEngine()
        sources = [
            SourceStatus("a", available=True, required=True),
            SourceStatus("b", available=False, required=True),
            SourceStatus("c", available=False, required=False),
        ]
        result = engine.assess(sources)
        assert result.sources_required == 2  # only required sources


class TestReductionsJsonRoundTrip:
    def test_reductions_json_is_valid(self):
        engine = ConfidenceEngine()
        sources = [SourceStatus("access_control", available=False, required=True)]
        result = engine.assess(sources, llm_unavailable=True)

        parsed = json.loads(result.reductions_json)
        assert isinstance(parsed, list)
        assert len(parsed) == 2
        for item in parsed:
            assert "reason" in item
            assert "amount" in item
            assert "source_id" in item
            assert "detail" in item

    def test_empty_reductions_json(self):
        engine = ConfidenceEngine()
        result = engine.assess(sources=[])
        assert result.reductions_json == "[]"


class TestCustomReductionAmounts:
    def test_custom_amount_overrides_default(self):
        """Constructor override changes the reduction amount for the specified reason."""
        engine = ConfidenceEngine(
            reduction_amounts={ConfidenceReduction.SOURCE_UNAVAILABLE: 0.05}
        )
        sources = [SourceStatus("access_control", available=False, required=True)]
        result = engine.assess(sources)

        assert result.confidence_score == pytest.approx(0.95)
        assert result.reductions[0].amount == 0.05

    def test_unspecified_reasons_retain_defaults(self):
        """Only overridden reasons change; others keep their defaults."""
        engine = ConfidenceEngine(
            reduction_amounts={ConfidenceReduction.SOURCE_UNAVAILABLE: 0.05}
        )
        result = engine.assess(sources=[], llm_unavailable=True)
        # LLM reduction is still the default 0.20
        assert result.confidence_score == pytest.approx(0.80)


class TestAdr004NoDatabaseRequired:
    def test_confidence_engine_requires_no_db_session(self):
        """
        ADR-004 — Confidence Engine is purely synchronous and requires no DB.
        Instantiation and assess() must succeed without any database dependency.
        """
        # No session argument — must work without one
        engine = ConfidenceEngine()
        sources = [
            SourceStatus("access_control", available=True),
            SourceStatus("schedule", available=False, required=True),
        ]
        result = engine.assess(sources)
        assert result.confidence_score == pytest.approx(0.80)
        assert result.confidence_level == "high"
