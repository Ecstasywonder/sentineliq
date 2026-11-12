# Gate 23 — MVP usability and operator-validation readiness

**Status:** 🟡 Candidate implementation; not complete

Gate 23 covers the five canonical MVP demonstration scenarios in §51 of the
[Master Build Prompt](master-build-prompt.md), the operator-dashboard journeys,
and the accessibility requirement that risk is communicated in text as well as
colour. Completion requires a repaired scenario runner, fresh EC2 evidence, a
passing protected-branch CI run, and merge to `main`.

## Scenario assets

[`data/scenarios/mvp-scenarios.json`](../data/scenarios/mvp-scenarios.json)
contains the candidate entries with `gate23_scenario` labels A–E:

| ID | Scenario | Intended operator outcome |
|---|---|---|
| `demo-scenario-a` | Authorized activity | Low-risk assessment; operator may dismiss after review. |
| `demo-scenario-b` | Unverified after-hours event | High-risk assessment and escalation path. |
| `demo-scenario-c` | Missing evidence | Explicit unavailable evidence and reduced confidence. |
| `demo-scenario-d` | Conflicting evidence | Conflict and uncertainty visible to the operator. |
| `demo-scenario-e` | AI unavailable | Safe deterministic behaviour and manual review. |

These are scenario intentions, not yet verified end-to-end evidence. The
candidate implementation uses a versioned, server-owned demo assessment profile
for scenario-specific evidence and failure controls; it must never trust caller
metadata for those controls. The repaired runner and its evidence isolation
remain to be validated on EC2 before it can claim the five expected outcomes.

## Simulator contract

The implemented authenticated simulator endpoint is:

```text
POST /api/v1/simulator/generate
```

Example request:

```json
{"scenario_ids":["demo-scenario-b"],"persist":true}
```

Its response is an object, not a scenario catalogue or a bare results list:

```json
{
  "generated": 1,
  "persisted": 1,
  "duplicates": 0,
  "events": [
    {
      "scenario_id": "demo-scenario-b",
      "title": "…",
      "event": {"…": "…"},
      "persisted_event_id": "…",
      "duplicate": false
    }
  ]
}
```

`persisted_event_id` is the identifier to pass to
`POST /api/v1/events/{id}/assess`. The older simulator persist route and its
scenario-catalogue endpoint are not implemented.

## Candidate UI coverage

[`frontend/src/test/demo_scenarios.test.tsx`](../frontend/src/test/demo_scenarios.test.tsx)
contains candidate journey coverage for the scenario displays and accessible
risk labels. Its count and pass status must be recorded only after the current
EC2 run; historical counts are deliberately not used as release evidence.

The dashboard implementation provides the intended queue, event-detail,
human-decision, escalation, audit, and risk-text surfaces. End-to-end operator
validation remains pending against the current deployed build.

## Outstanding exit evidence

- [ ] Validate the repaired `scripts/run_demo_scenarios.sh` against the
  `/simulator/generate` contract and `events[].persisted_event_id` response
  shape.
- [ ] Verify the versioned, isolated scenario preparation for Scenario C
  evidence unavailability, Scenario D conflict, and Scenario E AI failure;
  do not infer them from event metadata alone.
- [ ] Run the repaired runner on the isolated EC2 test environment and retain
  sanitized results.
- [ ] Run current backend and frontend validation on EC2.
- [ ] Pass protected-branch CI and merge the verified commit to `main`.
- [ ] Record the exact commit, commands, test counts, and results here.

Until those items are complete, Gate 23 is not a release-ready usability
validation and cannot be used as evidence for Gate 24 or Gate 25.
