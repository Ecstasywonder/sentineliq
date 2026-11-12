# Gate 23 — MVP usability and operator-validation readiness

**Status:** 🟡 EC2-verified candidate; merge to `main` pending

Gate 23 covers the five canonical MVP demonstration scenarios in §51 of the
[Master Build Prompt](master-build-prompt.md), the operator-dashboard journeys,
and the accessibility requirement that risk is communicated in text as well as
colour. Completion requires a repaired scenario runner, fresh EC2 evidence, a
passing protected-branch CI run, and merge to `main`.

## Scenario assets

[`data/scenarios/mvp-scenarios.json`](../data/scenarios/mvp-scenarios.json)
contains the entries with `gate23_scenario` labels A–E:

| ID | Scenario | Intended operator outcome |
|---|---|---|
| `demo-scenario-a` | Authorized activity | Low-risk assessment; operator may dismiss after review. |
| `demo-scenario-b` | Unverified after-hours event | High-risk assessment and escalation path. |
| `demo-scenario-c` | Missing evidence | Explicit unavailable evidence and reduced confidence. |
| `demo-scenario-d` | Conflicting evidence | Conflict and uncertainty visible to the operator. |
| `demo-scenario-e` | AI unavailable | Safe deterministic behaviour and manual review. |

The candidate implementation uses a versioned, server-owned demo assessment
profile for scenario-specific evidence and failure controls; it never trusts
caller metadata for those controls. On 2026-11-12, the repaired runner passed
all 73 assertions across Scenarios A-E against a disposable EC2 database/API
stack at commit `993c0fe`. The stack was removed after the run, so no shared
demonstration data was mutated.

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
contains journey coverage for the scenario displays and accessible risk labels.
The current EC2 validation at `993c0fe` passed all 57 frontend unit tests,
including the scenario and text-label coverage, as well as typecheck, lint,
format verification, and the production build.

The dashboard implementation provides the intended queue, event-detail,
human-decision, escalation, audit, and risk-text surfaces. End-to-end operator
validation remains pending against the final deployed `main` build.

## Current validation evidence

- Candidate commit: `993c0fe` (`fix/orchestrate-reconcile-access`).
- Gate 23 runner: 73 passed, 0 failed on a disposable EC2 stack. This includes
  high-confidence checks for Scenarios A/B, named unavailable sources and no
  false badge-absence assertion for C, explicit conflict/reduction checks for
  D, and the visible AI-unavailable deterministic path for E.
- Backend: 816 passed, 3 skipped, 91% coverage on EC2; the focused security,
  simulator, tool, configuration, and migration set passed 103 tests.
- Frontend: format, typecheck, lint, 57 unit tests, and production build passed
  on EC2.
- PostgreSQL: fresh upgrade, downgrade to base, and re-upgrade through Alembic
  revision `0006_unique_service_purpose` passed on EC2.
- Protected-branch CI: all backend, frontend, Gitleaks, and Trivy jobs passed in
  [GitHub Actions run 43232697244](https://github.com/Ecstasywonder/sentineliq/actions/runs/43232697244).

## Remaining exit evidence

- [ ] Merge the verified candidate to `main` after final live-Orchestrate and
  documentation review.
- [ ] Re-run the public/operator journey against the deployed `main` revision;
  production keeps the simulator route disabled, so use authorized ingestion
  or a separately controlled non-production validation environment.

The EC2 results are valid Gate 24 candidate evidence, but Gate 23 remains
strictly incomplete until the verified commit is merged to `main`.
