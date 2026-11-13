# Gate 17 — Sentinel Coordinator

**Document ID:** SNTL-GATE-017  
**Version:** 1.0  
**Date:** 2026-11-07  
**Author:** IBM Bob (Principal Architect)  
**Branch:** `main`  
**Status:** ✅ Complete

---

## Objective

Implement the **Sentinel Coordinator** — the orchestrating agent that provides
a read-only review of an already-assessed security event by delegating to the
Triage, Context, and Explanation specialist agents via watsonx Orchestrate.

Per the master build prompt (§14.1) and master gate plan Gate 17:

> The Coordinator is a read-only reviewer. The transactional workflow
> authority (event state, risk scoring, confidence) remains the backend
> `AssessmentService`. The Coordinator reads persisted assessment data and
> structures a final review for the operator.

---

## Requirements Implemented

| Ref | Requirement | Status |
|-----|-------------|--------|
| §14.1 | Coordinator receives event-assessment request and delegates to specialists | ✅ (read-only review, not write-path assessment) |
| §14.1 | Must preserve human-review state | ✅ (`human_review_required=True` always enforced) |
| §14.1 | Coordinator must not invent evidence | ✅ (agent output validated, then operator fields rebuilt from persisted rows) |
| §33 | Coordinator has read-only tool access | ✅ (`get_event_detail` + `get_assessment_bundle` only) |
| §34 | Agent invocation, run ID, latency captured | ✅ (`AgentRun` row persisted for every call) |
| §10 | AI unavailable → event not lost | ✅ (deterministic fallback always returns `CoordinatorReview`) |
| §28 | Agent output treated as untrusted | ✅ (strict Pydantic schema, event_id override, forbidden word filter) |
| ADR-003 | No risk scoring by LLM | ✅ (Coordinator reads risk from DB; never recalculates) |
| ADR-006 | Human review non-bypassable | ✅ (`human_review_required=True` is a `const: true` in output schema) |

---

## Scope Delivered

| Deliverable | File | Status |
|---|---|---|
| Coordinator schemas | `backend/app/schemas/coordinator.py` | ✅ |
| CoordinatorService (Orchestrate + deterministic) | `backend/app/services/coordinator_service.py` | ✅; current grounding fix pending merge/deploy |
| GET `/api/v1/events/{id}/review` endpoint | `backend/app/api/v1/endpoints/coordinator.py` | ✅ |
| Router registration | `backend/app/api/v1/router.py` | ✅ |
| 37 tests | `backend/tests/test_coordinator.py` | ✅ |
| Gate report | `docs/gate-17-coordinator.md` | ✅ |
| Master gate plan updated | `docs/master-gate-plan.md` | ✅ |

---

## Architecture

### Pipeline position

The Coordinator sits **after** AssessmentService has completed the deterministic
pipeline. It is invoked on demand by an operator who wants a structured
agent-generated review:

```
POST /events/{id}/assess   [AssessmentService]
  → triage → evidence → context → risk → confidence → explanation → recommendation
  → event.status = awaiting_review

GET /events/{id}/review    [CoordinatorService]  ← Gate 17
  → load persisted assessment bundle from DB
  → invoke Orchestrate Coordinator agent (Path B)
     ↳ collaborators: sentinel_triage_agent, sentinel_context_agent, sentinel_explanation_agent
  → OR deterministic fallback if Orchestrate unavailable (Path 0)
  → persist AgentRun row
  → return CoordinatorReview (read-only, event state unchanged)
```

### Two invocation paths

| Path | Condition | Mechanism |
|---|---|---|
| **B — Orchestrate SaaS** | `settings.orchestrate_active == True` AND `orchestrate_coordinator_agent_id` set | IAM bearer token → `/v1/orchestrate/<uuid>/chat/completions` |
| **0 — Deterministic fallback** | Both above unavailable or any failure | Reads persisted RiskAssessment + SecurityEvent rows, no LLM |

The service never exposes a Path A (watsonx.ai Chat API) because the
Coordinator's role is reviewing structured persisted data, not free-form
text generation. The deterministic fallback is sufficient and safe.

### Design constraints honoured

| Constraint | ADR | How honoured |
|---|---|---|
| Agent output is untrusted | All | Strict Pydantic `CoordinatorAgentOutput`; `extra="forbid"` |
| event_id always server-side | ADR-028 | `event_id` from agent is discarded; server value substituted |
| human_review_required always True | ADR-006 | Hardcoded in `_parse_and_validate`; `const: true` in agent schema |
| Coordinator cannot score risk | ADR-003 | No risk fields in `CoordinatorReview`; review reads DB values |
| Forbidden words removed | §19 | `_sanitise_summary()` replaces forbidden vocabulary |
| AgentRun always persisted | §34 | Row created at start of every `run()` call |
| Event never lost on failure | §10 | Deterministic fallback catches all exceptions |

---

## API

### `GET /api/v1/events/{event_id}/review`

**Permission required:** `events:read`  
**Allowed event statuses:** `awaiting_review`, `escalated`

**Response (200):**
```json
{
  "event_id": "evt-abc123",
  "assessment_ready": true,
  "summary": "Assessment complete for person_detected at LOADING_DOCK_3. Risk level is high, confidence is medium. Human review is required before any operational action is taken.",
  "missing_evidence": [],
  "human_review_required": true,
  "source": "deterministic_fallback",
  "agent_run_id": "a1b2c3d4-..."
}
```

**Error responses:**

| Code | Condition |
|------|-----------|
| 404  | Event not found |
| 409  | Event not in `awaiting_review` or `escalated` status |

---

## Tests

**Total tests added: 37**

| Test class | Count | Coverage |
|---|---|---|
| `TestDeterministicFallback` | 9 | assessment_ready T/F, summary content, missing evidence, source label |
| `TestParseAndValidate` | 8 | valid output, event_id override, human_review forced, non-JSON, schema error, markdown strip, forbidden words, summary truncation |
| `TestCoordinatorServiceRun` | 4 | fallback in test env, AgentRun persisted, Orchestrate failure → fallback, event_id returned |
| `TestCoordinatorAPI` | 11 | 200 awaiting_review, 200 escalated, 409 normalised, 409 closed, 404 unknown, human_review_required, source, assessment_ready T/F, missing_evidence list |

**Test commands (run on EC2):**
```bash
cd ~/sentineliq/backend
source .venv/bin/activate
APP_ENV=development SECRET_KEY=ci-test-secret-key \
DATABASE_URL="sqlite+aiosqlite:///:memory:" \
DATABASE_URL_SYNC="sqlite:///:memory:" \
uv run pytest tests/test_coordinator.py -v --tb=short

# Full suite
APP_ENV=development SECRET_KEY=ci-test-secret-key \
DATABASE_URL="sqlite+aiosqlite:///:memory:" \
DATABASE_URL_SYNC="sqlite:///:memory:" \
uv run pytest tests/ -v --tb=short --cov=app --cov-report=term-missing --cov-fail-under=85
```

---

## Manual Verification

1. Ingest an event and assess it:
```bash
# Ingest
curl -X POST http://localhost:8000/api/v1/events \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"event_type":"person_detected","event_timestamp":"2026-11-07T22:00:00Z","location_id":"LOADING_DOCK_3","zone":"restricted_after_hours","detector_confidence":0.94,"camera_id":"CAM-DOCK-03"}'

# Assess
curl -X POST http://localhost:8000/api/v1/events/$EVT_ID/assess \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{}'

# Review (Coordinator)
curl -X GET http://localhost:8000/api/v1/events/$EVT_ID/review \
  -H "Authorization: Bearer $TOKEN"
```

2. Expected: `human_review_required=true`, `assessment_ready=true`, `source` reflects `deterministic_fallback` (or `orchestrate` when Orchestrate is configured).

3. Check `agent_runs` table:
```sql
SELECT id, agent_name, status, duration_ms FROM agent_runs
WHERE agent_name = 'sentinel_coordinator' ORDER BY created_at DESC LIMIT 5;
```

---

## Security Review

| Item | Finding |
|------|---------|
| Agent output is untrusted | ✅ Strict Pydantic schema, `extra="forbid"` |
| event_id injection blocked | ✅ Server-side event_id always substituted |
| Forbidden language | ✅ `_sanitise_summary()` replaces prohibited vocabulary |
| Coordinator cannot change event state | ✅ No state-machine calls in CoordinatorService |
| Coordinator cannot score risk | ✅ Risk values read from DB only |
| human_review_required | ✅ Hardcoded `True` — cannot be overridden by agent output |
| AgentRun input_summary | ✅ Only safe bundle keys included — no raw evidence text |

---

## Known Limitations

1. **Live validation is complete but must be repeated after deployment** — On
   2026-11-13 Coordinator executed event-detail and assessment tools and made
   bounded calls to all three declared collaborators. Its observed UUID is
   `0e56991e-cd11-4f77-812f-ced7b31aeac7`; re-import can change it. Repeat this
   proof after merge, CI, and deployment of the grounding fix.

2. **No Path A (watsonx.ai)** — The Coordinator is designed for Orchestrate's collaborator-agent architecture. It does not have a watsonx.ai fallback — the deterministic fallback is the safety net.

3. **Structured output compatibility** — ReAct Core does not support native
   `structured_output`. The agent's exact JSON schema is in its instructions;
   backend Pydantic validation and persisted-data reconstruction enforce the
   contract. The latter prevents collaborator hallucinations from becoming
   operator-facing facts.

---

## Acceptance Criteria

| Criterion | Status |
|-----------|--------|
| `CoordinatorService.run()` always returns a `CoordinatorReview` | ✅ |
| Deterministic fallback reads persisted DB assessment | ✅ |
| `human_review_required=True` in all paths | ✅ |
| `event_id` always set to server-side value | ✅ |
| Forbidden words removed from summary | ✅ |
| `AgentRun` row persisted for every call | ✅ |
| `GET /api/v1/events/{id}/review` returns 200 for reviewable events | ✅ |
| 409 returned for non-reviewable status | ✅ |
| 37 new tests added | ✅ |
| Existing test suite unaffected | ⚠️ EC2 focused regression evidence exists; rerun after final merge/deploy |

---

## Next Gate

**Gate 18 — Agent Tool Schemas (OpenAPI → Orchestrate)**

Formalize and validate all Orchestrate tool schemas against the live backend
OpenAPI contract, ensuring every tool definition used by triage, context,
explanation, and coordinator agents is schema-valid and traceable to the
running backend.
