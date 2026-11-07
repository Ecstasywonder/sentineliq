# Gate 21 — Evaluation Framework

**Status:** ✅ Complete  
**Date:** 2026-11-07  
**Branch:** main  
**Tests:** 744 backend (all passing) · 39 frontend (all passing) · 15 scorer unit tests (all passing)

---

## Objective

Create the evaluation framework — dataset, expected outputs, automated scoring,
and baseline evaluation report — as specified in Master Build Prompt Gate 21.

---

## Deliverables

| File | Description |
|------|-------------|
| `evaluations/datasets/eval-dataset.json` | 30 synthetic evaluation cases |
| `evaluations/expected/output-schema.json` | Expected output schema + 12 scoring rules |
| `evaluations/scoring/scorer.py` | Automated scoring engine |
| `evaluations/scoring/test_eval_dataset.py` | 15 pure-Python dataset + scorer unit tests |
| `backend/tests/test_evaluation_pipeline.py` | 106 live pipeline tests (ADR-003/004/006) |
| `evaluations/reports/eval-baseline-gate-21.md` | Baseline evaluation report |

---

## Evaluation Dataset

**30 synthetic evaluation cases** covering all 26 named scenario categories from Master Build Prompt §35:

| Category | Count |
|----------|-------|
| Normal / authorized activity | 4 |
| Authorized after-hours work | 1 |
| Authorized / unexpected delivery | 2 |
| After-hours presence (no badge) | 1 |
| Invalid badge / restricted area | 1 |
| Unavailable access / schedule system | 2 |
| Schedule mismatch | 1 |
| Restricted / unrestricted location | 2 |
| Recent similar incidents / no history | 2 |
| Contradictory / stale / missing evidence | 3 |
| Severe alarm event | 1 |
| Malformed input / duplicate event | 2 |
| Prompt injection / irrelevant / misleading evidence | 3 |
| Risk/confidence quadrants (all 4 combinations) | 4 |
| LLM unavailable / vehicle event / all adapters timeout | 3 |

Each case specifies: input event, simulated evidence state, expected triage category,
expected risk range, expected confidence range, required context sources, prohibited behaviors.

---

## Automated Scoring

The scorer (`scorer.py`) runs 12 weighted checks per case:

| Check | Weight | Notes |
|-------|--------|-------|
| triage_category_correct | 1.0 | |
| risk_level_correct | 1.0 | |
| risk_score_in_range | 1.0 | |
| confidence_level_correct | 1.0 | |
| confidence_score_in_range | 1.0 | |
| **human_review_preserved** | **2.0** | ADR-006 — safety invariant |
| **no_llm_risk_score** | **2.0** | ADR-003 — safety invariant |
| **confidence_independent_of_risk** | **2.0** | ADR-004 — safety invariant |
| confidence_reduction_on_missing | 1.5 | |
| required_context_complete | 1.0 | |
| **prohibited_behavior_absent** | **2.0** | Safety invariant |
| **event_not_lost** | **2.0** | Safety invariant |

Safety invariants (5 checks) are double-weighted. Pass criteria: safety invariants 100%, overall ≥ 90%.

---

## Pipeline Tests Added

**`backend/tests/test_evaluation_pipeline.py`** — 106 tests:

| Test | Parametrized | Description |
|------|-------------|-------------|
| `test_triage_never_raises_on_eval_case` | 30 cases | Event-not-lost for all eval cases |
| `test_triage_never_produces_risk_score` | 30 cases | ADR-003 for all eval cases |
| `test_triage_always_returns_required_context` | 30 cases | ADR-006 for all eval cases |
| `test_confidence_independent_of_risk_all_eval_cases` | 1 | ADR-004 structural test |
| `test_evidence_aggregator_never_raises_on_eval_case` | 15 cases | Aggregator robustness |

**`evaluations/scoring/test_eval_dataset.py`** — 15 pure-Python tests:

- Dataset structure validation (fields, uniqueness, spec coverage)
- Scorer logic (pass case, safety violation detection, report generation)

---

## Validation Results

```
ruff check app/ tests/ evaluations/scoring/   All checks passed!
ruff format --check app/ tests/ evaluations/scoring/  126 files already formatted
pytest tests/ -q --tb=short                   744 passed, 2 warnings in 30.05s
pytest evaluations/scoring/test_eval_dataset.py -v    15 passed in 0.03s
npm run typecheck                             ✓ no errors
npm run lint                                  ✓ 0 warnings
npm run test:unit                             39 passed
npm run build                                 ✓ built in 110ms
```
