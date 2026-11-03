# Gate 4 — Deterministic Risk Engine & Confidence Engine

**Date:** 2026-11-03  
**Gate:** 4  
**Status:** Complete  
**Author:** IBM Bob (Principal Architect)

---

## 1. Scope

Gate 4 delivers the two core scoring engines that underpin every security event assessment in SentinelIQ.  These engines are **the most architecturally critical components in the backend**: they enforce the ADR-003 (deterministic risk) and ADR-004 (risk ≠ confidence) constraints at the code level.

| Engine | Module | Type |
|--------|--------|------|
| Risk Engine | `app/services/risk_engine.py` | Async (DB-backed) |
| Confidence Engine | `app/services/confidence_engine.py` | Sync (pure Python) |

---

## 2. Risk Engine

### 2.1 Design Principles

- Score is computed from **policy factors stored in the database** — no hard-coded weights in application logic.
- The LLM **never** produces, modifies, or overrides a risk score.
- Every factor contribution is captured in `factors_json` for full audit reproducibility.
- Score is clamped to `[0, 200]` to prevent pathological edge cases.
- Policy version is explicit on every result — historical reconstruction is always possible.

### 2.2 Scoring Algorithm

```
raw_score = Σ (factor.weight × 1 if signal.triggered else 0)
           for each active factor in the policy

clamped_score = max(0, min(200, raw_score))

risk_level = classify(clamped_score, policy.thresholds_json)
```

### 2.3 Risk Level Classification (v1.0 policy)

| Score Range | Level |
|-------------|-------|
| 0 – 24 | LOW |
| 25 – 49 | MEDIUM |
| 50 – 74 | HIGH |
| 75+ | CRITICAL |

### 2.4 Default Factors (v1.0 policy — from seed data)

| Factor ID | Weight | Direction |
|-----------|--------|-----------|
| `no_matching_badge` | +25 | increases_risk |
| `outside_schedule` | +20 | increases_risk |
| `restricted_area` | +25 | increases_risk |
| `no_work_order` | +15 | increases_risk |
| `recent_incidents` | +10 | increases_risk |
| `forced_door_alarm` | +40 | increases_risk |
| `approved_maintenance` | −30 | decreases_risk |
| `valid_access_schedule` | −35 | decreases_risk |

### 2.5 Safe Fallbacks

| Condition | Behaviour |
|-----------|-----------|
| Policy version not found | Returns score=0.0, level=low, factors=[] |
| Signal factor_id not in policy | Signal silently ignored |
| Inactive policy factor | Excluded from scoring |
| Malformed `thresholds_json` | Falls back to hardcoded defaults |

---

## 3. Confidence Engine

### 3.1 Design Principles

- Confidence starts at **1.0** and is reduced by each applicable factor.
- Missing evidence reduces **confidence only** — never risk (ADR-004).
- The engine is **pure Python** (no DB session required) — can run anywhere.
- All reduction reasons and amounts are enumerated as `ConfidenceReduction` constants, stable across versions.

### 3.2 Scoring Algorithm

```
score = 1.0
for each applicable reduction:
    score -= reduction_amount

confidence_score = max(0.0, min(1.0, score))
confidence_level = classify(confidence_score)
```

### 3.3 Confidence Level Classification

| Score | Level |
|-------|-------|
| 0.80 – 1.0 | HIGH |
| 0.50 – 0.79 | MEDIUM |
| 0.00 – 0.49 | LOW |

### 3.4 Reduction Catalogue

| Reason | Default Amount | Applies When |
|--------|---------------|--------------|
| `source_unavailable` | −0.20 | Required source not reachable |
| `source_stale` | −0.10 | Source data exceeds freshness window |
| `contradictory_evidence` | −0.15 | Two evidence items contradict each other |
| `incomplete_event_metadata` | −0.10 | Event missing required fields |
| `tool_retrieval_error` | −0.10 | Tool raised an exception (per erroring source) |
| `llm_unavailable` | −0.20 | Explanation Agent could not run |

### 3.5 Key Rules

- **Optional sources** (`required=False`) do NOT reduce confidence when unavailable.
- A source that is unavailable AND stale triggers only `source_unavailable` (not both).
- `tool_retrieval_error` and `source_unavailable` are **independent** — a source can trigger both if it was both unreachable and threw an error.
- Reduction amounts are **overridable** via the `ConfidenceEngine` constructor for calibration without code changes.

---

## 4. Files Delivered

| File | Purpose |
|------|---------|
| `backend/app/services/risk_engine.py` | Risk Engine — 222 lines |
| `backend/app/services/confidence_engine.py` | Confidence Engine — 265 lines |
| `backend/tests/test_risk_engine.py` | Risk Engine tests — 291 lines, 14 test functions |
| `backend/tests/test_confidence_engine.py` | Confidence Engine tests — 285 lines, 32 test functions |
| `backend/alembic/env.py` | Fixed — uses `create_async_engine` + `asyncpg` URL rewrite |
| `docs/deployment.md` | Updated with Gate 4 test run commands |

---

## 5. BRD Demo Scenario Coverage

| Scenario | BRD Ref | Test | Expected Result |
|----------|---------|------|----------------|
| A — Authorised Activity | §11 | `test_scenario_a_authorised_activity` | LOW risk (score 0, clamped) |
| B — Unverified After-Hours | §11 | `test_scenario_b_unverified_after_hours` | HIGH risk (score 70) |
| C — Missing Evidence | §11 | `test_scenario_c_missing_evidence` | MEDIUM risk (score 40); confidence reduced |
| D — Conflicting Evidence | §11 | `test_scenario_d_critical_event` | CRITICAL risk (score 120) |
| E — AI Unavailable | §11 | `test_scenario_e_ai_unavailable_deterministic_score` | MEDIUM risk (score 45); engine unaffected by AI state |

---

## 6. ADR Compliance Verification

| ADR | Constraint | How Enforced |
|-----|-----------|-------------|
| ADR-003 | Risk score is deterministic, never LLM-produced | Risk Engine is pure math on DB factors; no LLM call path exists |
| ADR-003 | Factors and weights stored in DB, not hard-coded | `RiskPolicy` / `RiskPolicyFactor` tables; engine queries them every call |
| ADR-004 | Risk ≠ Confidence — computed independently | Separate classes, separate result types; `RiskResult` has no confidence fields |
| ADR-004 | Missing evidence → reduced confidence, NOT increased risk | `ConfidenceEngine` is the only consumer of `SourceStatus.available`; `RiskEngine` never sees it |
| ADR-006 | Human review non-bypassable | Neither engine initiates any action; they produce results for human review |

---

## 7. Acceptance Criteria — Gate 4

- [x] `RiskEngine.assess()` implemented and tested
- [x] `ConfidenceEngine.assess()` implemented and tested
- [x] All five BRD demo scenarios covered in Risk Engine tests
- [x] Score clamping tested (upper and lower bounds)
- [x] Policy-not-found safe fallback tested
- [x] Inactive factor exclusion tested
- [x] ADR-004 independence verified in `test_risk_and_confidence_independence`
- [x] `ConfidenceEngine` requires no DB session (ADR-004 purity test)
- [x] All reduction types covered in Confidence Engine tests
- [x] Optional source unavailability confirmed non-reducing
- [x] `reductions_json` and `factors_json` round-trip tested
- [x] `docs/deployment.md` updated with Gate 4 run commands

---

## 8. Next Gate

**Gate 5 — Event Ingestion API**

Will produce:
- `POST /api/v1/events` — ingest, normalise, deduplicate, persist
- `GET /api/v1/events/{id}` — retrieve event with assessment
- Event lifecycle state machine enforcement
- Pydantic schemas for all event types
- Full integration tests against the in-memory test DB
