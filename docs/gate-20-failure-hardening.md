# Gate 20 — Integration and Failure-State Hardening

**Status:** ✅ Complete  
**Date:** 2026-11-07  
**Branch:** main  
**Tests:** 638 backend (all passing) · 39 frontend (all passing)

---

## Objective

Prove that SentinelIQ degrades safely under every failure mode listed in the
Master Build Prompt.  No failure scenario may cause an unhandled exception,
a lost event, an altered risk score, or a bypassed human-review step.

---

## Failure Scenarios Covered

| # | Scenario | Mechanism | Pass Criterion |
|---|----------|-----------|----------------|
| 1 | Unavailable access system | `EvidenceAggregator._safe()` isolates `RuntimeError`/`ConnectionError` | Error in `result.errors["access_events"]`; other sources unaffected |
| 2 | Unavailable schedule system | Same `_safe()` isolation | Error in `result.errors["schedule"]`; access unaffected |
| 3 | Unavailable LLM | `TriageService` 3-path fallback → Path 0 (deterministic) | `result.source == "deterministic_fallback"`; never raises |
| 4 | Missing incident history | `gather()` returns empty records section, no error | `record_count == 0`; `"incident_history" not in errors` |
| 5 | Contradictory evidence | `ContextService` conflict detection | `ctx.has_conflicts` is bool; `ctx.missing_sources` is list |
| 6 | Malformed tool output | `_safe()` absorbs `ValueError`, `KeyError` | `result.errors` populated; section is `None` |
| 7 | Timeout | `httpx.TimeoutException` caught by `_safe()` / triage fallback | Error captured; triage falls to deterministic |
| 8 | Stale source | `IntegrationHealth` rows with `consecutive_failures > 0` | Record surfaces in health response; assessment not blocked |
| 9 | Duplicate event | `POST /events` dedup via `provider_event_id` | First: 201; second: 200 + `Duplicate-Event: true` header |

---

## Tests Added

**File:** `backend/tests/test_failure_hardening.py` — 30 tests, 9 classes

| Class | Tests |
|-------|-------|
| `TestUnavailableAccessSystem` | 3 |
| `TestUnavailableScheduleSystem` | 2 |
| `TestUnavailableLLM` | 4 |
| `TestMissingHistory` | 3 |
| `TestContradictoryEvidence` | 2 |
| `TestMalformedToolOutput` | 3 |
| `TestTimeout` | 3 |
| `TestStaleSource` | 3 |
| `TestDuplicateEvent` | 4 |
| `TestSafeDegradationInvariants` | 3 |

---

## Architecture Invariants Verified

- **ADR-003**: LLM never produces a risk score — `TriageResult` has no `risk_score`/`risk_level` field.
- **ADR-004**: Missing evidence → confidence reduction only, not risk increase — `conf_fail.confidence_score ≤ conf_full.confidence_score`.
- **ADR-006**: Human review non-bypassable — all triage paths terminate with `TriageResult`; no path skips to decision.

---

## Key API Signatures Confirmed

```python
# ConfidenceEngine
SourceStatus(source_id="...", available=True/False, stale=False, required=True)
ConfidenceResult.confidence_score  # not .score

# ContextService
await ctx_svc.run(
    event_id,
    event_metadata=...,
    required_context=triage.required_context,  # list[str], not triage_result=
    evidence=...,
)

# IntegrationHealth model
last_checked_at: str | None  # store as ISO string, not datetime object
```

---

## Validation Results

```
ruff check app/ tests/       All checks passed!
ruff format --check app/ tests/  122 files already formatted
pytest tests/ -q --tb=short  638 passed, 2 warnings in 30.00s
npm run typecheck             ✓ no errors
npm run lint                  ✓ 0 warnings
npm run test:unit             39 passed
npm run build                 ✓ built in 112ms
```
