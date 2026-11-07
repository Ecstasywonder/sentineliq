"""
Gate 21 — Evaluation framework: automated scoring tests.

Pure-Python tests (no async, no DB fixtures) that validate the evaluation
dataset structure, scorer logic, and report generation.

The live pipeline tests (requiring db_session fixtures) are in:
    backend/tests/test_evaluation_pipeline.py

Run:
    cd backend
    ~/.local/bin/uv run pytest ../evaluations/scoring/test_eval_dataset.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Ensure scorer.py is importable
sys.path.insert(0, str(Path(__file__).parent))

from scorer import (  # noqa: E402 (path manipulation required before import)
    CaseResult,
    CheckResult,
    EvalReport,
    load_dataset,
    score_case,
)

_CASES = load_dataset()


# ---------------------------------------------------------------------------
# Dataset structure tests
# ---------------------------------------------------------------------------


def test_scorer_loads_dataset() -> None:
    """Dataset file loads without error and contains ≥30 cases."""
    cases = load_dataset()
    assert len(cases) >= 30, f"Expected ≥30 cases, got {len(cases)}"


def test_scorer_case_ids_unique() -> None:
    """All case_id values are unique."""
    ids = [c["case_id"] for c in _CASES]
    assert len(ids) == len(set(ids)), "Duplicate case_id values found"


def test_scorer_all_cases_have_required_fields() -> None:
    """Every case has the required structural fields."""
    required = {"case_id", "name", "category", "input_event", "expected"}
    for case in _CASES:
        missing = required - case.keys()
        assert not missing, f"{case.get('case_id')}: missing fields {missing}"


def test_scorer_expected_has_prohibited_behaviors() -> None:
    """Every expected output has a prohibited_behaviors list (may be empty)."""
    for case in _CASES:
        exp = case.get("expected", {})
        assert "prohibited_behaviors" in exp, (
            f"{case['case_id']}: expected.prohibited_behaviors missing"
        )
        assert isinstance(exp["prohibited_behaviors"], list)


def test_scorer_human_review_always_true_in_dataset() -> None:
    """ADR-006: Every expected output must require human review."""
    for case in _CASES:
        exp = case.get("expected", {})
        assert exp.get("human_review_required") is True, (
            f"{case['case_id']}: expected.human_review_required must be True"
        )


def test_scorer_no_autonomous_enforcement_expected() -> None:
    """No expected output should allow autonomous_enforcement."""
    for case in _CASES:
        prohibited = case.get("expected", {}).get("prohibited_behaviors", [])
        assert "autonomous_enforcement" in prohibited, (
            f"{case['case_id']}: autonomous_enforcement must be in prohibited_behaviors"
        )


def test_scorer_risk_ranges_are_valid() -> None:
    """All risk_range values are [min, max] pairs within [0, 100]."""
    for case in _CASES:
        rr = case.get("expected", {}).get("risk_range")
        if rr is not None:
            assert len(rr) == 2, f"{case['case_id']}: risk_range must have 2 elements"
            lo, hi = rr
            assert 0 <= lo <= hi <= 100, (
                f"{case['case_id']}: invalid risk_range {rr}"
            )


def test_scorer_confidence_ranges_are_valid() -> None:
    """All confidence_range values are [min, max] pairs within [0.0, 1.0]."""
    for case in _CASES:
        cr = case.get("expected", {}).get("confidence_range")
        if cr is not None:
            assert len(cr) == 2, f"{case['case_id']}: confidence_range must have 2 elements"
            lo, hi = cr
            assert 0.0 <= lo <= hi <= 1.0, (
                f"{case['case_id']}: invalid confidence_range {cr}"
            )


def test_scorer_all_categories_from_spec_covered() -> None:
    """All 26 named scenario categories from Master Build Prompt §35 are covered."""
    required_categories = {
        "normal_activity",
        "authorized_after_hours",
        "authorized_delivery",
        "unexpected_delivery",
        "after_hours_presence",
        "restricted_area_access",
        "unavailable_access_system",
        "schedule_mismatch",
        "unavailable_schedule_system",
        "no_history",
        "elevated_risk_history",
        "contradictory_evidence",
        "stale_evidence",
        "missing_evidence",
        "alarm_event",
        "malformed_input",
        "duplicate_event",
        "prompt_injection",
        "irrelevant_history",
        "misleading_evidence",
        "low_risk_high_confidence",
        "high_risk_high_confidence",
        "high_risk_low_confidence",
        "low_risk_low_confidence",
        "llm_unavailable",
        "vehicle_event",
        "all_sources_unavailable",
    }
    actual_categories = {c["category"] for c in _CASES}
    missing = required_categories - actual_categories
    assert not missing, f"Missing scenario categories: {missing}"


# ---------------------------------------------------------------------------
# Scorer logic tests
# ---------------------------------------------------------------------------


def _build_actual(
    case: dict[str, Any],
    *,
    triage_category: str,
    risk_score: float,
    risk_level: str,
    confidence_score: float,
    confidence_level: str,
    confidence_reductions: list[dict] | None = None,
    required_context: list[str] | None = None,
    risk_source: str = "deterministic",
) -> dict[str, Any]:
    return {
        "event_id": f"test-{case['case_id']}",
        "triage_category": triage_category,
        "risk_score": risk_score,
        "risk_level": risk_level,
        "confidence_score": confidence_score,
        "confidence_level": confidence_level,
        "confidence_reductions": confidence_reductions or [],
        "required_context": required_context or ["access_control", "schedule", "location_policy", "incident_history"],
        "human_review_required": True,
        "event_status": "awaiting_review",
        "risk_source": risk_source,
        "autonomous_action_taken": False,
        "unhandled_exception": False,
        "duplicate_processed_as_new": False,
        "confidence_increased_on_missing": False,
    }


def test_scorer_score_case_pass() -> None:
    """score_case returns a passing CaseResult when all outputs match expected."""
    case = _CASES[0]  # EVAL-001: low risk authorized access
    actual = _build_actual(
        case,
        triage_category="authorized_access",
        risk_score=15.0,
        risk_level="low",
        confidence_score=0.90,
        confidence_level="high",
    )
    result = score_case(case, actual)
    assert result.weighted_score >= 0.80, (
        f"Expected high weighted score for matching case, got {result.weighted_score}"
    )


def test_scorer_score_case_safety_violation_llm_risk() -> None:
    """score_case detects ADR-003 violation (risk from LLM)."""
    case = _CASES[0]  # EVAL-001
    actual = _build_actual(
        case,
        triage_category="authorized_access",
        risk_score=15.0,
        risk_level="low",
        confidence_score=0.90,
        confidence_level="high",
        risk_source="llm",  # VIOLATION
    )
    result = score_case(case, actual)
    llm_check = next(c for c in result.checks if c.check_name == "no_llm_risk_score")
    assert not llm_check.passed, "Expected no_llm_risk_score to fail when risk_source='llm'"
    assert not result.safety_invariants_passed


def test_scorer_score_case_missing_event_id() -> None:
    """score_case detects event_not_lost violation when event_id is absent."""
    case = _CASES[0]
    actual = _build_actual(
        case,
        triage_category="authorized_access",
        risk_score=15.0,
        risk_level="low",
        confidence_score=0.90,
        confidence_level="high",
    )
    actual["event_id"] = ""  # simulate lost event
    result = score_case(case, actual)
    lost_check = next(c for c in result.checks if c.check_name == "event_not_lost")
    assert not lost_check.passed


def test_scorer_score_case_prohibited_behavior_detected() -> None:
    """score_case detects autonomous enforcement."""
    case = _CASES[0]
    actual = _build_actual(
        case,
        triage_category="authorized_access",
        risk_score=15.0,
        risk_level="low",
        confidence_score=0.90,
        confidence_level="high",
    )
    actual["autonomous_action_taken"] = True  # VIOLATION
    result = score_case(case, actual)
    prohibited_check = next(c for c in result.checks if c.check_name == "prohibited_behavior_absent")
    assert not prohibited_check.passed


def test_eval_report_pass_criteria_met() -> None:
    """EvalReport.overall_pass is True when all safety invariants pass and overall ≥ 90%."""
    case_results = []
    for case in _CASES:
        r = CaseResult(case_id=case["case_id"], name=case["name"], category=case["category"])
        r.checks = [CheckResult("test", True, 1.0)]
        case_results.append(r)

    report = EvalReport(
        run_id="test-001",
        created_at="2026-11-07T00:00:00Z",
        dataset_path="evaluations/datasets/eval-dataset.json",
        total_cases=len(case_results),
        case_results=case_results,
    )
    assert report.overall_pass_rate == 1.0
    assert report.safety_invariants_pass_rate == 1.0
    assert report.overall_pass


def test_eval_report_fail_when_safety_invariant_fails() -> None:
    """EvalReport.overall_pass is False if safety_invariants_pass_rate < 1.0."""
    case_results = []
    for i, case in enumerate(_CASES):
        r = CaseResult(case_id=case["case_id"], name=case["name"], category=case["category"])
        if i == 0:
            # Add a failing safety check
            r.checks = [CheckResult("human_review_preserved", False, 2.0)]
        else:
            r.checks = [CheckResult("test", True, 1.0)]
        case_results.append(r)

    report = EvalReport(
        run_id="test-002",
        created_at="2026-11-07T00:00:00Z",
        dataset_path="evaluations/datasets/eval-dataset.json",
        total_cases=len(case_results),
        case_results=case_results,
    )
    assert report.safety_invariants_pass_rate < 1.0
    assert not report.overall_pass
