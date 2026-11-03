# Gate 9 — Risk Assessment API

**Status:** ✅ Complete  
**Date:** 2026-11-03  
**Author:** IBM Bob (Principal Architect)

---

## Summary

Gate 9 delivers the read-side of the risk assessment surface.  Operators and auditors
can now retrieve every persisted assessment without re-running the pipeline, inspect
the per-factor contribution breakdown in isolation, and enumerate the active risk
policies that govern scoring.

Three new endpoints are wired and tested:

| Method | Path | Permission | Description |
|--------|------|-----------|-------------|
| `GET` | `/api/v1/events/{id}/assessment` | `events:read` | Full assessment bundle (risk + confidence) |
| `GET` | `/api/v1/events/{id}/assessment/factors` | `events:read` | Per-factor risk breakdown only |
| `GET` | `/api/v1/risk-policies` | `admin:policy` | List all risk policy versions |
| `GET` | `/api/v1/risk-policies/{id}` | `admin:policy` | Single policy with all factor definitions |

All responses are read from DB rows written by Gate 8's `POST /assess`.  
No re-computation occurs in any Gate 9 endpoint.

---

## Deliverables

### 1 · `GET /api/v1/events/{id}/assessment`

Returns the full persisted assessment for an event.

**Response** (`AssessmentRetrievalResponse`):
```json
{
  "assessment_id": "...",
  "event_id": "...",
  "risk_policy_version": "1.0",
  "risk_score": 90.0,
  "risk_level": "high",
  "risk_factors": [
    { "factor_id": "after_hours_access", "label": "After Hours Access",
      "weight": 40.0, "direction": "increase", "triggered": true, "contribution": 40.0 }
  ],
  "confidence_score": 0.8,
  "confidence_level": "high",
  "confidence_reductions": [],
  "sources_available": 6,
  "sources_required": 6,
  "assessed_at": "2026-11-03T22:30:00+00:00",
  "agent_run_id": null
}
```

**Error codes:**

| Code | Body code | Reason |
|------|-----------|--------|
| 404 | `EVENT_NOT_FOUND` | Event UUID does not exist |
| 404 | `ASSESSMENT_NOT_FOUND` | Event exists but has never been assessed |

---

### 2 · `GET /api/v1/events/{id}/assessment/factors`

Focused view — risk factors only.  Designed for the Evidence/Factor Panel UI (Gate 23)
where only the contribution breakdown is needed without the full confidence context.

**Response** (`AssessmentFactorsResponse`):
```json
{
  "assessment_id": "...",
  "event_id": "...",
  "risk_policy_version": "1.0",
  "risk_score": 90.0,
  "risk_level": "high",
  "factors": [
    { "factor_id": "after_hours_access", "label": "After Hours Access",
      "weight": 40.0, "direction": "increase", "triggered": true, "contribution": 40.0 },
    { "factor_id": "unverified_person", "label": "Unverified Person",
      "weight": 50.0, "direction": "increase", "triggered": false, "contribution": 0.0 }
  ],
  "assessed_at": "2026-11-03T22:30:00+00:00"
}
```

**Invariants enforced by tests:**
- Triggered factors always have `contribution > 0`
- Untriggered factors always have `contribution == 0.0`
- `risk_score` matches the value in the full assessment response

---

### 3 · `GET /api/v1/risk-policies`

Returns all policy versions ordered by version descending.
Factor list is omitted per item for performance (`factors: []`).

**Response** (`RiskPolicyListResponse`):
```json
{
  "items": [{ "id": "...", "version": "1.0", "name": "Default v1.0",
              "is_active": true, "effective_from": null, "factors": [] }],
  "total": 1
}
```

---

### 4 · `GET /api/v1/risk-policies/{id}`

Returns the full policy definition including all factor rows ordered by weight descending.

**Response** (`RiskPolicyResponse`):
```json
{
  "id": "...",
  "version": "1.0",
  "name": "Default v1.0",
  "is_active": true,
  "factors": [
    { "factor_id": "unverified_person", "label": "Unverified Person",
      "weight": 50.0, "direction": "increase", "is_active": true }
  ]
}
```

---

## Files Changed / Added

| File | Change |
|------|--------|
| `backend/app/schemas/assessment.py` | Added `AssessmentFactorsResponse` schema |
| `backend/app/api/v1/endpoints/events.py` | Added `GET /{event_id}/assessment/factors` endpoint |
| `backend/app/api/v1/endpoints/risk_policies.py` | New — `GET /risk-policies` + `GET /risk-policies/{id}` |
| `backend/app/api/v1/router.py` | Mounted `risk_policies` router at `/risk-policies` |
| `backend/tests/test_assessment_retrieval.py` | New — 7 tests for `GET /assessment` |
| `backend/tests/test_assessment_factors.py` | New — 11 tests for `GET /assessment/factors` |
| `backend/tests/test_risk_policy_api.py` | New — 12 tests for risk policy endpoints |

---

## ADR Compliance

| ADR | Constraint | Enforced By |
|-----|-----------|-------------|
| ADR-003 | LLM never produces risk score | GET endpoints read DB rows — no computation |
| ADR-004 | Risk ≠ Confidence (independent) | `AssessmentRetrievalResponse` keeps both separate |
| ADR-006 | Human review non-bypassable | Read endpoints do not change event state |

---

## Test Coverage

### `test_assessment_retrieval.py` — 7 tests

| Test | What it checks |
|------|---------------|
| `test_returns_200_after_assess` | Basic GET after assess |
| `test_response_shape` | All required fields present and typed |
| `test_risk_factors_deserialized` | Factors list contains correct sub-fields |
| `test_scores_match_assess_response` | GET scores equal POST /assess scores |
| `test_assessment_id_matches_db_row` | `assessment_id` matches `RiskAssessment.id` |
| `test_404_for_unknown_event` | `EVENT_NOT_FOUND` for unknown UUID |
| `test_404_for_unassessed_event` | `ASSESSMENT_NOT_FOUND` for never-assessed event |
| `test_reassess_updates_retrieval` | GET returns latest values after re-assess |

### `test_assessment_factors.py` — 11 tests

| Test | What it checks |
|------|---------------|
| `test_returns_200` | Basic 200 after assess |
| `test_response_shape` | Top-level fields present and typed |
| `test_factors_non_empty` | At least one factor returned |
| `test_each_factor_shape` | All factor sub-fields present |
| `test_factors_match_assess_response` | Factor IDs / weights / contributions match POST /assess |
| `test_risk_score_matches_assessment` | risk_score matches full assessment |
| `test_triggered_factor_has_nonzero_contribution` | Triggered → contribution > 0 |
| `test_untriggered_factor_has_zero_contribution` | Not triggered → contribution == 0 |
| `test_404_for_unknown_event` | `EVENT_NOT_FOUND` |
| `test_404_for_unassessed_event` | `ASSESSMENT_NOT_FOUND` |

### `test_risk_policy_api.py` — 12 tests

| Test | What it checks |
|------|---------------|
| `test_returns_200` | List returns 200 |
| `test_response_shape` | items + total fields |
| `test_includes_seeded_policy` | Seeded version appears in list |
| `test_list_items_have_no_factors` | List view omits factors |
| `test_total_matches_item_count` | total == len(items) |
| `test_returns_200` (single) | Single GET returns 200 |
| `test_response_shape` (single) | id / version / name / is_active / factors |
| `test_factors_included` | Factors list has ≥ 2 items |
| `test_factor_shape` | Each factor has required fields |
| `test_factors_ordered_by_weight_desc` | Heaviest factor first |
| `test_404_for_unknown_id` | `POLICY_NOT_FOUND` |
| `test_is_active_field` | `is_active=False` reflected correctly |

**Total Gate 9 tests: 30**  
**Cumulative test suite: ~238**

---

## Next Gate

**Gate 10 — Operator Decision API**

- `POST /api/v1/events/{id}/decision` — record operator decision (approve/dismiss/escalate)
- `GET /api/v1/events/{id}/decision` — retrieve persisted decision
- Decision model: `operator_decisions` table (Gate 3), decision types, notes, reviewer identity
- Status machine: `awaiting_review` → `approved` / `dismissed` / `escalated`
- Audit trail entry on every decision
