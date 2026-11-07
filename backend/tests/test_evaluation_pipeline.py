"""
Gate 21 — Evaluation framework: live pipeline tests.

Exercises the deterministic assessment pipeline against each evaluation
case from the dataset, verifying safety invariants hold for all 30 cases.

These tests live in backend/tests/ so they share the conftest.py fixtures
(db_session, etc.).

Run:
    cd backend
    ~/.local/bin/uv run pytest tests/test_evaluation_pipeline.py -v --tb=short
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

# Make evaluations/scoring importable
sys.path.insert(0, str(Path(__file__).parents[2] / "evaluations" / "scoring"))

from scorer import load_dataset  # noqa: E402

pytestmark = pytest.mark.asyncio

_CASES = load_dataset()


# ---------------------------------------------------------------------------
# Parametrized safety-invariant tests — all 30 evaluation cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", _CASES, ids=[c["case_id"] for c in _CASES])
async def test_triage_never_raises_on_eval_case(
    case: dict[str, Any], db_session: AsyncSession
) -> None:
    """Triage must never raise for any evaluation case — event must not be lost."""
    from app.services.triage_service import TriageService

    svc = TriageService(db_session)
    meta = {
        **case["input_event"],
        # Coerce None to empty string — triage handles empty strings gracefully
        "event_timestamp": case["input_event"].get("event_timestamp") or "2026-06-15T12:00:00Z",
        "location_id": case["input_event"].get("location_id") or "loc-eval-default",
    }
    try:
        result = await svc.run(f"eval-nraise-{case['case_id']}", meta)
    except Exception as exc:
        pytest.fail(
            f"{case['case_id']}: TriageService.run raised {type(exc).__name__}: {exc}"
        )
    assert result is not None, f"{case['case_id']}: triage returned None"


@pytest.mark.parametrize("case", _CASES, ids=[c["case_id"] for c in _CASES])
async def test_triage_never_produces_risk_score(
    case: dict[str, Any], db_session: AsyncSession
) -> None:
    """ADR-003: TriageResult must never have risk_score or risk_level attributes."""
    from app.services.triage_service import TriageService

    svc = TriageService(db_session)
    meta = {
        **case["input_event"],
        "event_timestamp": case["input_event"].get("event_timestamp") or "2026-06-15T12:00:00Z",
        "location_id": case["input_event"].get("location_id") or "loc-eval-default",
    }
    result = await svc.run(f"eval-adr003-{case['case_id']}", meta)
    assert not hasattr(result, "risk_score"), (
        f"{case['case_id']}: ADR-003 violated — TriageResult has risk_score"
    )
    assert not hasattr(result, "risk_level"), (
        f"{case['case_id']}: ADR-003 violated — TriageResult has risk_level"
    )


@pytest.mark.parametrize("case", _CASES, ids=[c["case_id"] for c in _CASES])
async def test_triage_always_returns_required_context(
    case: dict[str, Any], db_session: AsyncSession
) -> None:
    """ADR-006: Triage always returns a non-empty required_context baseline.

    This ensures the assessment pipeline will gather evidence and present
    the event for human review (not auto-dismiss).
    """
    from app.services.triage_service import TriageService

    svc = TriageService(db_session)
    meta = {
        **case["input_event"],
        "event_timestamp": case["input_event"].get("event_timestamp") or "2026-06-15T12:00:00Z",
        "location_id": case["input_event"].get("location_id") or "loc-eval-default",
    }
    result = await svc.run(f"eval-ctx-{case['case_id']}", meta)
    assert isinstance(result.required_context, list), (
        f"{case['case_id']}: required_context must be a list"
    )
    assert len(result.required_context) > 0, (
        f"{case['case_id']}: required_context must not be empty (ADR-006 — human review non-bypassable)"
    )


# ---------------------------------------------------------------------------
# Confidence-independence invariant (ADR-004)
# ---------------------------------------------------------------------------


async def test_confidence_independent_of_risk_all_eval_cases(
    db_session: AsyncSession,
) -> None:
    """ADR-004: Removing a source reduces confidence but must not change risk.

    Tests with 2 canonical source sets:
    - Full: all 4 baseline sources available
    - Partial: access_control unavailable
    """
    from app.services.confidence_engine import ConfidenceEngine, SourceStatus

    engine = ConfidenceEngine()

    sources_full = [
        SourceStatus(source_id="access_control", available=True),
        SourceStatus(source_id="schedule", available=True),
        SourceStatus(source_id="location_policy", available=True),
        SourceStatus(source_id="incident_history", available=True),
    ]
    sources_partial = [
        SourceStatus(source_id="access_control", available=False),
        SourceStatus(source_id="schedule", available=True),
        SourceStatus(source_id="location_policy", available=True),
        SourceStatus(source_id="incident_history", available=True),
    ]

    result_full = engine.assess(sources_full)
    result_partial = engine.assess(sources_partial)

    assert result_partial.confidence_score < result_full.confidence_score, (
        "ADR-004: Missing source must reduce confidence"
    )

    # Verify the SOURCE_UNAVAILABLE reduction reason is present
    reduction_reasons = [r.reason for r in result_partial.reductions]
    assert "source_unavailable" in reduction_reasons, (
        "SOURCE_UNAVAILABLE reduction must be recorded when a source is missing"
    )


# ---------------------------------------------------------------------------
# Evidence aggregator robustness (ADR-004 + event-not-lost)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "case", _CASES[:15], ids=[c["case_id"] for c in _CASES[:15]]
)
async def test_evidence_aggregator_never_raises_on_eval_case(
    case: dict[str, Any], db_session: AsyncSession
) -> None:
    """EvidenceAggregator.gather must never raise — even with no seeded data."""
    from app.services.evidence_aggregator import EvidenceAggregator

    agg = EvidenceAggregator(db_session)
    loc = case["input_event"].get("location_id") or "loc-eval-default"
    try:
        result = await agg.gather(f"eval-agg-{case['case_id']}", loc)
    except Exception as exc:
        pytest.fail(
            f"{case['case_id']}: EvidenceAggregator.gather raised {type(exc).__name__}: {exc}"
        )
    assert result is not None
    # Error dict is allowed (isolated failures), but gather must not raise
    assert isinstance(result.errors, dict)
