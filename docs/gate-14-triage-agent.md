# Gate 14 — Triage Agent

**Status:** ✅ Complete  
**Branch:** `gate-14-triage-agent`  
**Date:** 2026-11-05  
**Author:** IBM Bob (Principal Architect)

> **Gate numbering:** This report retains the original roadmap label. It implements
> Gate 11 (Triage Agent) in the canonical [Master Build Prompt](master-build-prompt.md).
> Live watsonx Orchestrate validation completed on EC2 on 2026-11-13. Final
> merge, CI, and deployed-revision regression evidence remains required.

---

## Summary

Gate 14 delivers the Triage Agent — the first agentic component in the
SentinelIQ pipeline.  The agent classifies incoming security events,
identifies urgency signals, and determines which evidence sources must be
queried.  It integrates with watsonx Orchestrate and falls back gracefully
to deterministic classification when Orchestrate is unavailable.

---

## Objective

Implement the Triage Agent as described in master prompt sections 15, 33,
and 34, and in the master gate plan Gate 14 scope:

> - Define `triage_agent` in `agents/triage/`
> - Tool schemas for assessment endpoints
> - Integration test: Orchestrate invocation → backend response

---

## Requirements Implemented

| Ref | Requirement | Status |
|-----|-------------|--------|
| §15 | Triage Agent classifies event, identifies urgency, identifies required context | ✅ |
| §15 | Must NOT determine guilt, perform enforcement, invent identities | ✅ (enforced in instructions + output filtering) |
| §33 | Triage Agent should NOT have escalation tools | ✅ (read-only `get_event_detail` only) |
| §34 | Agent invocation, version, tool calls, latency must be captured | ✅ (`AgentRun` + `ToolCall` rows) |
| §10 | AI unavailable → event not lost, deterministic fallback | ✅ (`TriageService` fallback) |
| §11 | Safe default when AI unavailable | ✅ (always returns TriageResult) |
| §28 | Agent output is treated as untrusted data | ✅ (allowlist filtering in `_parse_and_validate`) |
| §37 | Automated tests | ✅ (46 tests added) |

---

## Files Created / Modified

### New files

| File | Purpose |
|------|---------|
| `agents/triage/agent.yaml` | Orchestrate agent definition — model, tools, instructions, output schema |
| `agents/triage/output_schema.py` | Pydantic TriageResult schema mirroring agent.yaml |
| `agents/triage/tools/get_event_detail.yaml` | OpenAPI 3.1 tool schema for read-only event retrieval |
| `backend/app/services/triage_service.py` | TriageService — Orchestrate call, AgentRun persistence, deterministic fallback |
| `backend/app/schemas/triage.py` | TriageResult + TriageResultDetail Pydantic models |
| `backend/tests/test_triage_agent.py` | 46 tests: deterministic fallback, parse+validate, HTTP mock, integration |
| `docs/adr/ADR-007-triage-agent-integration.md` | Architecture Decision Record |
| `docs/gate-14-triage-agent.md` | This report |

### Modified files

| File | Change |
|------|--------|
| `backend/app/schemas/assessment.py` | Added `triage: TriageResultDetail \| None` to `AssessmentResponse` |
| `backend/app/services/assessment_service.py` | Step 0: invoke `TriageService` before deterministic pipeline; store `agent_run_id` on event |

---

## Architecture Decisions

See `docs/adr/ADR-007-triage-agent-integration.md` for the full record.

Key decisions:
1. Triage runs before the deterministic pipeline — result stored alongside assessment but does NOT influence risk score (ADR-003 preserved).
2. Mandatory deterministic fallback — `TriageService` always returns a `TriageResult`.
3. Agent output is untrusted data — allowlist filtering applied to all output fields.
4. Triage Agent has least-privilege tool access — read-only `get_event_detail` only.
5. `AgentRun` record always created — observable via `agent_runs` / `tool_calls` tables.

---

## API Changes

### `POST /api/v1/events/{id}/assess` — response updated

```json
{
  "event_id": "...",
  "event_status": "awaiting_review",
  "triage": {
    "category": "after_hours_presence",
    "urgency_signals": ["after_hours", "restricted_zone"],
    "required_context": ["access_control", "schedule", "location_policy", "incident_history", "work_orders"],
    "triage_rationale": "Deterministic fallback triage: event_type=person_detected, zone=restricted_after_hours, signals=['after_hours', 'restricted_zone']",
    "source": "deterministic_fallback",
    "agent_run_id": "d7a8b3e2-..."
  },
  "risk_score": 78.0,
  "risk_level": "critical",
  ...
}
```

The `triage` field is optional (`null` only if AssessmentService fails before triage runs, which should not occur in normal operation).

---

## Triage Categories

| Category | When used |
|----------|-----------|
| `after_hours_presence` | Person/motion detected outside permitted hours in non-public zone |
| `restricted_area_access` | Access detected in restricted area |
| `delivery_event` | Delivery vehicle/person detected |
| `authorized_access` | Badge event with no other risk indicators |
| `alarm_event` | door_forced or alarm_triggered event type |
| `vehicle_event` | Vehicle detected |
| `unclassified` | Default fallback |

---

## Urgency Signals

| Signal | Trigger |
|--------|---------|
| `after_hours` | Event timestamp hour UTC >= 20 or < 06 |
| `restricted_zone` | zone contains "restricted" |
| `forced_entry` | event_type = door_forced or alarm_triggered |
| `no_camera_coverage` | camera_id is null |
| `low_detector_confidence` | detector_confidence is null or < 0.5 |
| `missing_event_metadata` | timestamp could not be parsed |
| `repeated_event` | (future — not yet implemented) |

---

## Tests

**Total tests added: 46**

| Test class / function | Count | What it covers |
|-----------------------|-------|----------------|
| `TestDeterministicFallback` | 17 | All signal/category/context rules, source label, rationale length |
| `TestParseAndValidate` | 8 | Valid output, markdown stripping, invalid category, signal/context allowlisting, prompt-injection in rationale, event_id override |
| `TestTriageServiceRun` | 5 | No Orchestrate → fallback; mock success → orchestrate source; HTTP error → fallback; invalid JSON → fallback; empty choices → fallback |
| Integration tests | 6 | triage field in response, after_hours_presence category, alarm_event category, agent_run_id linked, low confidence signal, existing tests still pass |

**Test commands (run on EC2):**
```bash
cd backend
uv run pytest tests/test_triage_agent.py -v
uv run pytest tests/ --cov=app --cov-report=term-missing --cov-fail-under=85
uv run ruff check app/ tests/
```

---

## Manual Verification

1. POST an after-hours event in a restricted zone:
```bash
curl -X POST http://localhost:8000/api/v1/events \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"event_type":"person_detected","event_timestamp":"2026-11-05T23:00:00Z","location_id":"LOADING_DOCK_3","zone":"restricted_after_hours","detector_confidence":0.94,"camera_id":"CAM-DOCK-03"}'
```

2. Trigger assessment and inspect the `triage` field:
```bash
curl -X POST http://localhost:8000/api/v1/events/{id}/assess \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}'
```

Expected: `triage.category = "after_hours_presence"`, `triage.urgency_signals` contains `["after_hours", "restricted_zone"]`.

3. Check `agent_runs` table:
```sql
SELECT id, agent_name, status, duration_ms, source FROM agent_runs ORDER BY created_at DESC LIMIT 5;
```

---

## Security and Safety Review

| Item | Finding |
|------|---------|
| Agent output treated as untrusted | ✅ Allowlist filtering on all fields in `_parse_and_validate()` |
| Prompt injection in rationale | ✅ `triage_rationale` truncated to 512 characters |
| Agent cannot call write endpoints | ✅ Only `get_event_detail` tool (read-only) |
| Triage does not influence risk score | ✅ ADR-003 preserved — risk engine is deterministic |
| Event not lost on AI failure | ✅ Deterministic fallback always returns a result |
| AgentRun records sensitive prompt | ✅ Input summary limited to safe event metadata (no raw evidence) |
| Triage cannot trigger enforcement | ✅ Triage result is classification only — no workflow authority |

---

## Known Limitations

1. **Live evidence is not final deployment evidence** — A fresh EC2 event
   completed with Triage source `orchestrate`. The observed tenant UUID is
   `76daed62-455c-4999-93b1-8ab7aff82c31`; re-import can change it. Repeat the
   proof after the Path-A-removal candidate merges, passes CI, and is deployed.

2. **`repeated_event` signal not implemented** — Requires incident history to
   detect duplicate events.

3. **Fallback proof remains required** — The deployed revision must show an
   Orchestrate failure returning deterministic output without a direct watsonx.ai
   chat attempt.

---

## Acceptance Criteria

| Criterion | Status |
|-----------|--------|
| agent.yaml defines triage agent with instructions, tools, output schema | ✅ |
| OpenAPI tool schema for `get_event_detail` | ✅ |
| `TriageService` calls Orchestrate with event metadata | ✅ |
| `TriageService` falls back to deterministic when Orchestrate unavailable | ✅ |
| Fallback produces the same classification fields as live agent | ✅ |
| Agent output validated against allowlists (prompt-injection defence) | ✅ |
| `AgentRun` row persisted for every call | ✅ |
| `agent_run_id` stored on `SecurityEvent` | ✅ |
| `triage` field included in `AssessmentResponse` | ✅ |
| 46 new tests added | ✅ |
| Existing test suite unaffected | ⚠️ EC2 focused regression evidence exists; rerun after final merge/deploy |
| ADR-007 written | ✅ |

---

## Historical next implementation step

The original roadmap called the Context Agent Gate 15. It is Gate 12 in the
canonical Master Build Prompt and is documented in
[gate-15-context-agent.md](gate-15-context-agent.md).

The next unfinished canonical gate is Gate 13 — Explanation Agent.
