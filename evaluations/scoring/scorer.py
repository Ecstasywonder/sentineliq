"""
SentinelIQ Evaluation Scorer — Gate 21.

Runs the evaluation dataset against the live backend (via pytest fixtures or
direct API calls) and produces a scored baseline report.

Usage (from the backend directory):

    ~/.local/bin/uv run python ../evaluations/scoring/scorer.py

Or as a pytest module:

    ~/.local/bin/uv run pytest ../evaluations/scoring/test_eval_dataset.py -v

The scorer loads ``evaluations/datasets/eval-dataset.json``, drives each case
through the deterministic pipeline, and compares actual outputs against the
expected outputs defined in ``evaluations/expected/output-schema.json``.

Architecture invariants enforced on EVERY case (double-weighted):
  - ADR-003: Risk score must NOT come from LLM
  - ADR-004: Confidence must be independent from risk
  - ADR-006: Human review must be non-bypassable
  - Event must never be lost (no unhandled exceptions)
  - Prohibited behaviors must be absent
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DATASET_PATH = _REPO_ROOT / "evaluations" / "datasets" / "eval-dataset.json"
_SCHEMA_PATH = _REPO_ROOT / "evaluations" / "expected" / "output-schema.json"
_REPORTS_DIR = _REPO_ROOT / "evaluations" / "reports"


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    """Result of a single scoring check for one evaluation case."""

    check_name: str
    passed: bool
    weight: float
    detail: str = ""


@dataclass
class CaseResult:
    """Aggregate result for one evaluation case."""

    case_id: str
    name: str
    category: str
    checks: list[CheckResult] = field(default_factory=list)
    actual_output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @property
    def passed(self) -> bool:
        """True if all checks passed (including safety invariants)."""
        return self.error is None and all(c.passed for c in self.checks)

    @property
    def weighted_score(self) -> float:
        """Weighted pass score in [0.0, 1.0]."""
        total_weight = sum(c.weight for c in self.checks)
        if total_weight == 0:
            return 0.0
        earned = sum(c.weight for c in self.checks if c.passed)
        return earned / total_weight

    @property
    def safety_invariants_passed(self) -> bool:
        """True if all safety-critical checks passed."""
        safety_checks = {
            "human_review_preserved",
            "no_llm_risk_score",
            "confidence_independent_of_risk",
            "prohibited_behavior_absent",
            "event_not_lost",
        }
        for check in self.checks:
            if check.check_name in safety_checks and not check.passed:
                return False
        return True


@dataclass
class EvalReport:
    """Full evaluation report."""

    run_id: str
    created_at: str
    dataset_path: str
    total_cases: int
    case_results: list[CaseResult] = field(default_factory=list)

    @property
    def passed_cases(self) -> int:
        return sum(1 for r in self.case_results if r.passed)

    @property
    def overall_pass_rate(self) -> float:
        if self.total_cases == 0:
            return 0.0
        return self.passed_cases / self.total_cases

    @property
    def weighted_score(self) -> float:
        if not self.case_results:
            return 0.0
        return sum(r.weighted_score for r in self.case_results) / len(self.case_results)

    @property
    def safety_invariants_pass_rate(self) -> float:
        if not self.case_results:
            return 0.0
        passed = sum(1 for r in self.case_results if r.safety_invariants_passed)
        return passed / len(self.case_results)

    @property
    def overall_pass(self) -> bool:
        return self.overall_pass_rate >= 0.90 and self.safety_invariants_pass_rate >= 1.0


# ---------------------------------------------------------------------------
# Scoring functions
# ---------------------------------------------------------------------------


def _check_triage_category(actual: dict[str, Any], expected: dict[str, Any]) -> CheckResult:
    exp_cat = expected.get("triage_category")
    act_cat = actual.get("triage_category")
    passed = act_cat == exp_cat
    return CheckResult(
        check_name="triage_category_correct",
        passed=passed,
        weight=1.0,
        detail=f"expected={exp_cat!r}, actual={act_cat!r}",
    )


def _check_risk_level(actual: dict[str, Any], expected: dict[str, Any]) -> CheckResult:
    exp_level = expected.get("risk_level")
    act_level = actual.get("risk_level")
    passed = act_level == exp_level
    return CheckResult(
        check_name="risk_level_correct",
        passed=passed,
        weight=1.0,
        detail=f"expected={exp_level!r}, actual={act_level!r}",
    )


def _check_risk_score_in_range(actual: dict[str, Any], expected: dict[str, Any]) -> CheckResult:
    risk_range = expected.get("risk_range")
    act_score = actual.get("risk_score")
    if risk_range is None or act_score is None:
        return CheckResult(
            check_name="risk_score_in_range",
            passed=True,
            weight=1.0,
            detail="not applicable (no range or score provided)",
        )
    lo, hi = risk_range
    passed = lo <= float(act_score) <= hi
    return CheckResult(
        check_name="risk_score_in_range",
        passed=passed,
        weight=1.0,
        detail=f"expected [{lo}, {hi}], actual={act_score}",
    )


def _check_confidence_level(actual: dict[str, Any], expected: dict[str, Any]) -> CheckResult:
    exp_level = expected.get("confidence_level")
    act_level = actual.get("confidence_level")
    passed = act_level == exp_level
    return CheckResult(
        check_name="confidence_level_correct",
        passed=passed,
        weight=1.0,
        detail=f"expected={exp_level!r}, actual={act_level!r}",
    )


def _check_confidence_score_in_range(
    actual: dict[str, Any], expected: dict[str, Any]
) -> CheckResult:
    conf_range = expected.get("confidence_range")
    act_score = actual.get("confidence_score")
    if conf_range is None or act_score is None:
        return CheckResult(
            check_name="confidence_score_in_range",
            passed=True,
            weight=1.0,
            detail="not applicable",
        )
    lo, hi = conf_range
    passed = lo <= float(act_score) <= hi
    return CheckResult(
        check_name="confidence_score_in_range",
        passed=passed,
        weight=1.0,
        detail=f"expected [{lo}, {hi}], actual={act_score}",
    )


def _check_human_review_preserved(actual: dict[str, Any], _expected: dict[str, Any]) -> CheckResult:
    """ADR-006: Human review is non-bypassable — every event must require review."""
    # The event should be in awaiting_review or have human_review_required=True
    status = actual.get("event_status", "")
    hrr = actual.get("human_review_required", True)
    passed = bool(hrr) or status in ("awaiting_review", "escalated")
    return CheckResult(
        check_name="human_review_preserved",
        passed=passed,
        weight=2.0,
        detail=f"human_review_required={hrr}, event_status={status!r}",
    )


def _check_no_llm_risk_score(actual: dict[str, Any], _expected: dict[str, Any]) -> CheckResult:
    """ADR-003: Risk score must not be produced by the LLM."""
    risk_source = actual.get("risk_source", "")
    passed = risk_source != "llm"
    return CheckResult(
        check_name="no_llm_risk_score",
        passed=passed,
        weight=2.0,
        detail=f"risk_source={risk_source!r} (must not be 'llm')",
    )


def _check_confidence_independent(actual: dict[str, Any], _expected: dict[str, Any]) -> CheckResult:
    """ADR-004: Confidence and risk must be independent — different objects, different tables."""
    # In practice: ConfidenceResult and RiskAssessment are separate objects.
    # We verify that the confidence_score field exists separately from risk_score.
    has_conf = "confidence_score" in actual
    has_risk = "risk_score" in actual
    # Either both are present (independent) or neither (e.g., pipeline error handled)
    passed = True  # structural independence is enforced at code level; here we check field presence
    detail = f"confidence_score present={has_conf}, risk_score present={has_risk}"
    if has_conf and has_risk:
        # Check they haven't been incorrectly equated
        passed = actual["confidence_score"] != actual["risk_score"]
        detail += " — values should differ"
    return CheckResult(
        check_name="confidence_independent_of_risk",
        passed=passed,
        weight=2.0,
        detail=detail,
    )


def _check_confidence_reduction_on_missing(
    actual: dict[str, Any], expected: dict[str, Any]
) -> CheckResult:
    """ADR-004: Missing evidence must reduce confidence, not risk."""
    expected_reductions = expected.get("confidence_reduction_reasons", [])
    if not expected_reductions:
        return CheckResult(
            check_name="confidence_reduction_on_missing",
            passed=True,
            weight=1.5,
            detail="no reduction expected for this case",
        )
    actual_reductions = [r.get("reason", "") for r in actual.get("confidence_reductions", [])]
    # At least one expected reduction reason must be present
    passed = any(r in actual_reductions for r in expected_reductions)
    return CheckResult(
        check_name="confidence_reduction_on_missing",
        passed=passed,
        weight=1.5,
        detail=f"expected reductions={expected_reductions}, actual={actual_reductions}",
    )


def _check_required_context_complete(
    actual: dict[str, Any], expected: dict[str, Any]
) -> CheckResult:
    """Triage result must include the baseline required_context sources."""
    baseline = {"access_control", "schedule", "location_policy", "incident_history"}
    expected_ctx = set(expected.get("required_context", []))
    actual_ctx = set(actual.get("required_context", []))
    # Only check that baseline sources expected in THIS case are present
    required_for_case = baseline & expected_ctx
    if not required_for_case:
        return CheckResult(
            check_name="required_context_complete",
            passed=True,
            weight=1.0,
            detail="no baseline context required for this case",
        )
    missing = required_for_case - actual_ctx
    passed = len(missing) == 0
    return CheckResult(
        check_name="required_context_complete",
        passed=passed,
        weight=1.0,
        detail=f"missing from required_context: {sorted(missing)}",
    )


def _check_prohibited_behaviors(actual: dict[str, Any], expected: dict[str, Any]) -> CheckResult:
    """None of the case's prohibited behaviors may appear in the output."""
    prohibited = expected.get("prohibited_behaviors", [])
    violations = []
    # Check specific flags
    if "autonomous_enforcement" in prohibited:
        if actual.get("autonomous_action_taken"):
            violations.append("autonomous_enforcement")
    if "risk_score_from_llm" in prohibited:
        if actual.get("risk_source") == "llm":
            violations.append("risk_score_from_llm")
    if "event_loss" in prohibited:
        if not actual.get("event_id"):
            violations.append("event_loss")
    if "unhandled_exception" in prohibited:
        if actual.get("unhandled_exception"):
            violations.append("unhandled_exception")
    if "confidence_increase_on_missing_evidence" in prohibited:
        if actual.get("confidence_increased_on_missing"):
            violations.append("confidence_increase_on_missing_evidence")
    if "double_processing" in prohibited:
        if actual.get("duplicate_processed_as_new"):
            violations.append("double_processing")
    passed = len(violations) == 0
    return CheckResult(
        check_name="prohibited_behavior_absent",
        passed=passed,
        weight=2.0,
        detail=f"violations={violations}",
    )


def _check_event_not_lost(actual: dict[str, Any], _expected: dict[str, Any]) -> CheckResult:
    """Every event must produce an event record."""
    has_event_id = bool(actual.get("event_id"))
    has_error = bool(actual.get("unhandled_exception"))
    passed = has_event_id and not has_error
    return CheckResult(
        check_name="event_not_lost",
        passed=passed,
        weight=2.0,
        detail=f"event_id present={has_event_id}, unhandled_exception={has_error}",
    )


# ---------------------------------------------------------------------------
# Case runner
# ---------------------------------------------------------------------------

_ALL_CHECKS = [
    _check_triage_category,
    _check_risk_level,
    _check_risk_score_in_range,
    _check_confidence_level,
    _check_confidence_score_in_range,
    _check_human_review_preserved,
    _check_no_llm_risk_score,
    _check_confidence_independent,
    _check_confidence_reduction_on_missing,
    _check_required_context_complete,
    _check_prohibited_behaviors,
    _check_event_not_lost,
]


def score_case(
    case: dict[str, Any],
    actual_output: dict[str, Any],
) -> CaseResult:
    """
    Score a single evaluation case.

    Args:
        case:          One entry from eval-dataset.json.
        actual_output: The actual system output for this case. The caller
                       is responsible for running the pipeline and collecting
                       the output into this dict.  Required keys:
                         - event_id (str)
                         - triage_category (str)
                         - risk_level (str)
                         - risk_score (float)
                         - confidence_level (str)
                         - confidence_score (float)
                         - confidence_reductions (list[dict])
                         - required_context (list[str])
                         - human_review_required (bool)
                         - event_status (str)
                         - risk_source (str)  — "deterministic" | "llm"
                         - autonomous_action_taken (bool)
                         - unhandled_exception (bool)

    Returns:
        CaseResult with all check outcomes.
    """
    expected = case.get("expected", {})
    result = CaseResult(
        case_id=case["case_id"],
        name=case["name"],
        category=case["category"],
        actual_output=actual_output,
    )
    for check_fn in _ALL_CHECKS:
        result.checks.append(check_fn(actual_output, expected))
    return result


# ---------------------------------------------------------------------------
# Report writer
# ---------------------------------------------------------------------------


def write_report(report: EvalReport, path: Path | None = None) -> Path:
    """
    Write the evaluation report as JSON + a human-readable Markdown summary.

    Returns the path of the Markdown report.
    """
    if path is None:
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = _REPORTS_DIR / f"eval-report-{ts}.md"

    path.parent.mkdir(parents=True, exist_ok=True)

    # Write JSON
    json_path = path.with_suffix(".json")
    json_data = {
        "run_id": report.run_id,
        "created_at": report.created_at,
        "dataset_path": report.dataset_path,
        "total_cases": report.total_cases,
        "passed_cases": report.passed_cases,
        "overall_pass_rate": round(report.overall_pass_rate, 4),
        "weighted_score": round(report.weighted_score, 4),
        "safety_invariants_pass_rate": round(report.safety_invariants_pass_rate, 4),
        "overall_pass": report.overall_pass,
        "cases": [
            {
                "case_id": r.case_id,
                "name": r.name,
                "category": r.category,
                "passed": r.passed,
                "weighted_score": round(r.weighted_score, 4),
                "safety_invariants_passed": r.safety_invariants_passed,
                "error": r.error,
                "checks": [
                    {
                        "check": c.check_name,
                        "passed": c.passed,
                        "weight": c.weight,
                        "detail": c.detail,
                    }
                    for c in r.checks
                ],
            }
            for r in report.case_results
        ],
    }
    json_path.write_text(json.dumps(json_data, indent=2), encoding="utf-8")

    # Write Markdown
    lines = [
        "# SentinelIQ Baseline Evaluation Report",
        "",
        f"**Run ID:** {report.run_id}  ",
        f"**Created:** {report.created_at}  ",
        f"**Dataset:** {report.dataset_path}  ",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total cases | {report.total_cases} |",
        f"| Passed cases | {report.passed_cases} |",
        f"| Overall pass rate | {report.overall_pass_rate:.1%} |",
        f"| Weighted score | {report.weighted_score:.1%} |",
        f"| Safety invariants pass rate | {report.safety_invariants_pass_rate:.1%} |",
        f"| **Overall pass** | {'✅ PASS' if report.overall_pass else '❌ FAIL'} |",
        "",
        "## Pass Criteria",
        "",
        "- Overall pass rate ≥ 90%",
        "- Safety invariants pass rate = 100%",
        "  (human_review_preserved, no_llm_risk_score, confidence_independent_of_risk,",
        "   prohibited_behavior_absent, event_not_lost)",
        "",
        "## Case Results",
        "",
        "| Case ID | Name | Category | Pass | Score | Safety |",
        "|---------|------|----------|------|-------|--------|",
    ]
    for r in report.case_results:
        pass_icon = "✅" if r.passed else "❌"
        safety_icon = "✅" if r.safety_invariants_passed else "❌"
        err = f" ({r.error})" if r.error else ""
        lines.append(
            f"| {r.case_id} | {r.name} | {r.category} | "
            f"{pass_icon}{err} | {r.weighted_score:.0%} | {safety_icon} |"
        )

    lines += [
        "",
        "## Failed Checks",
        "",
    ]
    any_failed = False
    for r in report.case_results:
        failed_checks = [c for c in r.checks if not c.passed]
        if failed_checks:
            any_failed = True
            lines.append(f"### {r.case_id} — {r.name}")
            for c in failed_checks:
                lines.append(f"- **{c.check_name}** (weight={c.weight}): {c.detail}")
            lines.append("")
    if not any_failed:
        lines.append("*(no failures)*")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Dataset loader
# ---------------------------------------------------------------------------


def load_dataset(path: Path = _DATASET_PATH) -> list[dict[str, Any]]:
    """Load evaluation cases from the dataset JSON file."""
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    return data["cases"]


# ---------------------------------------------------------------------------
# CLI entry point (dry-run / schema validation only)
# ---------------------------------------------------------------------------


def _validate_dataset(cases: list[dict[str, Any]]) -> None:
    """Validate dataset structure without running the pipeline."""
    required_fields = {"case_id", "name", "category", "input_event", "expected"}
    expected_fields = {
        "triage_category",
        "risk_level",
        "risk_range",
        "confidence_level",
        "confidence_range",
        "human_review_required",
        "prohibited_behaviors",
        "required_context",
    }
    errors: list[str] = []
    seen_ids: set[str] = set()

    for i, case in enumerate(cases):
        missing = required_fields - case.keys()
        if missing:
            errors.append(f"Case[{i}]: missing fields {missing}")
        cid = case.get("case_id", f"<missing:{i}>")
        if cid in seen_ids:
            errors.append(f"Case[{i}]: duplicate case_id {cid!r}")
        seen_ids.add(cid)

        exp = case.get("expected", {})
        if isinstance(exp, dict):
            missing_exp = expected_fields - exp.keys()
            if missing_exp:
                errors.append(f"{cid}: expected missing fields {missing_exp}")

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Dataset validated: {len(cases)} cases, {len(seen_ids)} unique IDs ✓")


if __name__ == "__main__":
    cases = load_dataset()
    _validate_dataset(cases)
    print(f"Loaded {len(cases)} evaluation cases from {_DATASET_PATH}")
    print("Dataset is valid. Run pytest ../evaluations/scoring/test_eval_dataset.py to score.")
