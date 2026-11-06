# Gate 15 — Context Agent

**Document ID:** SNTL-GATE-015  
**Version:** 1.0  
**Date:** 2026-11-06  
**Author:** IBM Bob (Principal Architect)  
**Branch:** `gate-14-triage-agent`  
**Status:** ✅ Complete

> **Gate numbering:** This report retains the original roadmap label. It implements
> Gate 12 (Context Agent) in the canonical [Master Build Prompt](master-build-prompt.md).
> Live watsonx Orchestrate tenant validation remains outstanding.

---

## Objective

Implement the **Context Agent** — the second AI agent in the SentinelIQ pipeline.
After evidence is gathered by `EvidenceAggregator` (Gate 7/8), the Context Agent
interprets each source's findings, identifies conflicts between sources, and produces
a structured `ContextResult` that flows into `AssessmentResponse`.

The agent follows the same three-path architecture as the Triage Agent (ADR-008):
- **Path B** — watsonx Orchestrate SaaS (activates when `ORCHESTRATE_URL` is set)
- **Path A** — watsonx.ai Chat API (activates when `WATSONX_*` vars are set, verified live)
- **Path 0** — Deterministic fallback (always available, no LLM required)

---

## Scope

| Deliverable | File | Status |
|---|---|---|
| Orchestrate agent definition | `agents/context/agent.yaml` | ✅ |
| Output schema (Pydantic) | `agents/context/output_schema.py` | ✅ |
| OpenAPI tool schemas (7) | `agents/context/tools/` | ✅ |
| Context schemas | `backend/app/schemas/context.py` | ✅ |
| ContextService (3-path) | `backend/app/services/context_service.py` | ✅ |
| AssessmentService wired | `backend/app/services/assessment_service.py` | ✅ |
| AssessmentResponse updated | `backend/app/schemas/assessment.py` | ✅ |
| Tests (25) | `backend/tests/test_context_agent.py` | ✅ |
| Gate report | `docs/gate-15-context-agent.md` | ✅ |

---

## Architecture

### Pipeline position

```
SecurityEvent
    │
    ▼ Gate 14
TriageService.run()          ── classifies event, produces required_context[]
    │
    ▼ Gate 7/8
EvidenceAggregator.gather()  ── collects all 7 evidence sources
    │
    ▼ Gate 15  ← THIS GATE
ContextService.run()         ── interprets evidence, detects conflicts
    │
    ▼ Gate 4
RiskEngine.assess()          ── deterministic risk score (ADR-003)
ConfidenceEngine.assess()    ── independent confidence (ADR-004)
```

### Key inputs to ContextService

| Input | Source |
|---|---|
| `event_id` | SecurityEvent.id |
| `event_metadata` | Event fields (type, timestamp, location, zone) |
| `required_context` | TriageResult.required_context (list of source names) |
| `evidence` | AggregatedEvidence from EvidenceAggregator |

### Key outputs (ContextResult → ContextResultDetail in AssessmentResponse)

| Field | Description |
|---|---|
| `source_statuses` | Per-source status: `verified_present` / `verified_absent` / `unavailable` / `not_requested` |
| `conflicts` | List of `EvidenceConflict` records (source_a, source_b, description) |
| `missing_sources` | Sources that are `unavailable` and were in `required_context` |
| `context_summary` | Two-sentence neutral factual summary (≤ 1024 chars) |
| `has_conflicts` | Boolean: any conflicts detected |
| `has_missing_sources` | Boolean: any required sources unavailable |
| `source` | Path that produced the result: `orchestrate` / `watsonx_ai` / `deterministic_fallback` |
| `agent_run_id` | UUID of the AgentRun row persisted for this call |

---

## Design constraints honoured

| Constraint | ADR | How honoured |
|---|---|---|
| Agent output is untrusted | ADR-003 | source_statuses keys filtered to `_KNOWN_SOURCES` allowlist; status values filtered to `_ALLOWED_STATUSES` |
| Missing evidence ≠ negative evidence | ADR-004 | Unavailable sources are flagged as `unavailable`, never inferred as absent |
| Conflict surfaced, not resolved | ADR-006 | `has_conflicts` is passed to `ConfidenceEngine`; human review decides |
| Event never lost on AI failure | ADR-007 | Path 0 is always available; `run()` never raises |
| Dual-path routing | ADR-008 | Identical three-path structure to TriageService |
| Neutral language | Master prompt §28 | System prompt explicitly forbids: criminal, intruder, suspicious person |

---

## ConfidenceEngine integration

Gate 14 wired triage into the pipeline. Gate 15 closes the loop on confidence:

```python
# Before Gate 15 (hardcoded False):
conf_result = conf_engine.assess(
    has_contradictory_evidence=False,  # placeholder
    ...
)

# After Gate 15 (live from ContextAgent):
conf_result = conf_engine.assess(
    has_contradictory_evidence=context_result.has_conflicts,  # real data
    ...
)
```

When the Context Agent detects a conflict (e.g. valid badge access in a restricted zone),
`has_conflicts=True` flows into the Confidence Engine and reduces the confidence score —
triggering mandatory human review as required by ADR-006.

---

## Deterministic conflict detection (Path 0)

Two conflict patterns are detected without an LLM:

| Pattern | Sources | Trigger |
|---|---|---|
| Valid badge in restricted zone | `access_control` + `location_policy` | `access_granted=True` AND any active restriction rule |
| Access denied with no schedule | `access_control` + `schedule` | `access_granted=False` AND `schedule` returned 0 records |

---

## OpenAPI tool schemas

Seven tool schemas are defined in `agents/context/tools/`:

| Tool | Operand |
|---|---|
| `get_access_events.yaml` | Badge/access-control log for a location |
| `get_schedule.yaml` | Scheduled-access windows for a location |
| `get_work_orders.yaml` | Active work orders for a location |
| `get_delivery_context.yaml` | Expected deliveries for a facility |
| `get_location_policy.yaml` | Security rules and zone classifications |
| `get_incident_history.yaml` | Prior incident records at a location |
| `get_event_detail.yaml` | Full metadata for a SentinelIQ event |

These are used by the Orchestrate agent definition (`agent.yaml`) for PATH B.
In PATH A, the `ContextService` passes a compact evidence summary directly to the
watsonx.ai Chat API — no tool calls required.

---

## Test results

```
=== RUFF ===
All checks passed!

=== PYTEST: Gate 15 context agent (25 tests) ===
25 passed in 0.17s

=== FULL SUITE ===
397 passed in 8.16s
Coverage: 92%
```

### Test classes

| Class / Test | Coverage |
|---|---|
| `TestDeterministicFallback` | 7 tests — source status classification, summary, truncation |
| `TestConflictDetection` | 3 tests — badge+policy conflict, denied+no-schedule, no-conflict |
| `TestParseAndValidate` | 8 tests — injection filtering, status normalisation, markdown strip |
| `TestCompactEvidence` | 2 tests — errors propagation, record detail limiting |
| `TestLLMPaths` | 4 tests — Path A success, A→0 fallback, no-creds→0, B→A fallback |
| `test_assess_response_includes_context` | Integration: endpoint returns context field |

---

## API change

`POST /api/v1/events/{id}/assess` now includes a `context` field in the response:

```json
{
  "event_id": "...",
  "triage": { "category": "access_anomaly", ... },
  "context": {
    "source_statuses": {
      "access_control": { "status": "verified_present", "record_count": 2, "summary": "..." },
      "schedule":       { "status": "verified_absent",  "record_count": 0, "summary": "..." }
    },
    "conflicts": [
      {
        "source_a": "access_control",
        "source_b": "schedule",
        "description": "An access-denied event was found, and no scheduled activity covers this location."
      }
    ],
    "missing_sources": [],
    "context_summary": "Two access records found. One conflict detected.",
    "has_conflicts": true,
    "has_missing_sources": false,
    "source": "deterministic_fallback",
    "agent_run_id": "..."
  },
  "risk_score": 0.72,
  ...
}
```

---

## No regressions

All 372 pre-existing tests from Gates 0–14 continue to pass.  
Gate 15 adds 25 new tests for a total of **397 tests**.
