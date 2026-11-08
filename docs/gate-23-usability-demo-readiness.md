# Gate 23 — MVP usability and operator validation readiness

Gate 23 prepares the five canonical MVP demonstration scenarios (§51 of the
Master Build Prompt), validates the operator dashboard journey through each,
and confirms accessibility requirements are met before the Gate 24 release
candidate is assembled.

---

## Scope

The gate requires:

1. Realistic demo scenarios covering every §51 required case.
2. A runnable demo scenario script that seeds and validates each scenario
   against the live API.
3. Frontend scenario journey tests proving the dashboard renders each
   expected state correctly.
4. Accessibility confirmation: risk communicated via text, not colour alone.

---

## Five canonical demo scenarios

The five scenarios were added to [`data/scenarios/mvp-scenarios.json`](../data/scenarios/mvp-scenarios.json)
as entries with `gate23_scenario` labels A through E. They carry stable
`provider_event_id` values (SIM-A through SIM-E) that do not collide with any
existing simulator fixture, and each includes a `description` field explaining
the expected assessment outcome.

| ID | Gate23 | Title | Expected risk |
|----|--------|-------|---------------|
| `demo-scenario-a` | A | Demo Scenario A — Authorized activity (low risk) | low |
| `demo-scenario-b` | B | Demo Scenario B — Unverified after-hours event (high risk) | high |
| `demo-scenario-c` | C | Demo Scenario C — Missing evidence (degraded confidence) | medium |
| `demo-scenario-d` | D | Demo Scenario D — Conflicting evidence | high |
| `demo-scenario-e` | E | Demo Scenario E — AI unavailable (deterministic fallback) | medium |

### Scenario A — Authorized activity

- Person detected at main entrance at 09:15 during business hours.
- Valid badge, scheduled activity, policy permits.
- **Expected**: low risk, meaningful confidence, operator can dismiss or confirm.

### Scenario B — Unverified after-hours event

- Person detected at Loading Dock 3 at 23:10.
- No matching badge, no scheduled activity, restricted area, prior incidents at same location.
- **Expected**: high or critical risk, high confidence (all evidence sources healthy),
  clear evidence factors visible, human review required.

### Scenario C — Missing evidence

- Person detected at Loading Dock 3; badge service and schedule service unavailable.
- **Expected**: sources marked unavailable, confidence reduced, no assertion that
  "no badge exists" (only that evidence is unavailable), human review requested.

### Scenario D — Conflicting evidence

- Badge event at server room; valid badge present but not scheduled, restricted area policy.
- **Expected**: conflict explicitly shown, confidence reflects uncertainty, human review.

### Scenario E — AI unavailable

- Motion detected in server room when AI assessment pipeline unavailable.
- **Expected**: event remains in queue, deterministic risk and evidence accessible,
  AI explanation marked unavailable, operator can manually review and record a decision.

---

## Demo scenario runner

[`scripts/run_demo_scenarios.sh`](../scripts/run_demo_scenarios.sh) seeds all
five Gate 23 scenarios via the API and verifies each produces the expected
assessment outcome. It is designed to run on the provisioned EC2 server against
a seeded database.

Usage:

```bash
E2E_ALLOW_PERSISTENT_WRITES=yes \
E2E_EMAIL=admin@example.com \
E2E_PASSWORD=yourpassword \
bash scripts/run_demo_scenarios.sh
```

The script shares the same HTTP helpers as `scripts/e2e_smoke.sh` and validates:

- Each scenario seeds and assesses without error.
- Scenario A produces `risk_level: low` and the event reaches `dismissed` status
  after an operator dismisses it.
- Scenario B produces `risk_level: high` or `critical`, a risk score ≥ 50, and
  the event escalates correctly via the `escalate` decision.
- Scenario C produces `confidence_reductions` and `evidence_errors` showing
  unavailable sources, and the operator can record a `request_context` decision.
- Scenario D produces `risk_level: high`, risk factors visible, and the operator
  can record an `accept` decision after reviewing the conflict.
- Scenario E completes deterministic assessment, the coordinator review uses the
  `deterministic_fallback` path, and the operator can record a `reject` decision
  without AI.
- All five events have an audit trail.
- The simulator scenario catalogue lists all five Gate 23 scenarios.

---

## Frontend scenario journey tests

[`frontend/src/test/demo_scenarios.test.tsx`](../frontend/src/test/demo_scenarios.test.tsx)
contains 21 Vitest tests covering all five scenarios plus accessibility. The
tests exercise the full operator journey using the existing test infrastructure
(`AuthProvider`, `fetch` mock, `@testing-library/react`).

| Suite | Tests |
|-------|-------|
| Scenario A — Authorized activity | Low risk text in queue; decision form visible; human review notice |
| Scenario B — Unverified after-hours | High risk text in queue; risk factors (badge/schedule/restricted); escalate option in select for supervisor |
| Scenario C — Missing evidence | Confidence reduction labels; missing evidence items without false assertions; "cannot confirm or deny" limitation |
| Scenario D — Conflicting evidence | Conflict text surfaced; uncertainty confidence; confidence reduction reason shown |
| Scenario E — AI unavailable | Deterministic risk score visible; AI unavailable limitation; Record decision form; coordinator review via deterministic fallback |
| Accessibility §30 | Low/medium/high/critical text labels in queue; accessible sign-in form |

All 57 frontend unit tests pass after this gate (34 original + 5 API + 18 new
Gate 23 scenario tests).

---

## Dashboard usability validation

The dashboard (Gates 16–19) already implements the §29 operator dashboard
requirements in full. The following points were confirmed against each scenario:

**Event queue (§29)**

- Event time, location, event type, risk level, confidence, and status are all
  rendered as text labels in each queue row.
- Risk level is never communicated by colour alone (§30): the queue renders the
  level name (Low / Medium / High / Critical) as visible text in every row.
- Sorting and filtering by risk, status, and facility are provided.

**Event detail (§29)**

- Event summary, risk level and score, confidence level and score, explanation
  summary, evidence list, missing evidence, limitations, recommendation, and
  timeline are all rendered.
- Triage and context agent results appear in the Agent panel.
- The coordinator review panel button is present for reviewable events.

**Human decision area (§29)**

- Decision select contains: accept, reject, dismiss, request context.
- Escalate is added for officer/supervisor/security\_admin/platform\_admin roles.
- Override is added for supervisor and above.
- A rationale textarea and a "Record decision" button are present.

**Accessibility (§30)**

- Risk communicated via text label in every risk-bearing element.
- Sign-in form inputs have accessible labels (`<label>` elements, not just
  placeholders).
- The sign-in submit is a `<button>` with a visible name.
- Decision controls use a `<select>` and a `<button>` with labelled text.

---

## Acceptance criteria

| Criterion | Result |
|-----------|--------|
| Five §51 demo scenarios added to `mvp-scenarios.json` with `gate23_scenario` labels A-E | ✅ |
| Scenario dataset validates through `load_scenarios()` (EventIngestRequest checked) | ✅ |
| `test_gate23_demo_scenarios_present` test passes | ✅ |
| `test_dataset_covers_all_required_scenario_types` updated to 24 scenarios | ✅ |
| `scripts/run_demo_scenarios.sh` created; seeds and validates all five scenarios | ✅ |
| `frontend/src/test/demo_scenarios.test.tsx` created; 18 scenario journey tests | ✅ |
| All 57 frontend unit tests pass | ✅ |
| All 780 backend tests pass | ✅ |
| Ruff check + format clean on `tests/test_simulator.py` | ✅ |
| Prettier clean on `src/test/demo_scenarios.test.tsx` | ✅ |
| Dashboard accessibility: risk text labels, labelled inputs, button roles | ✅ |

---

## Known limitations / future work

- `run_demo_scenarios.sh` targets the simulator persist endpoint
  (`POST /api/v1/simulator/events`). If the simulator API is disabled in
  production configuration, the script must be adapted to seed events via
  `POST /api/v1/events` directly.
- The "AI unavailable" scenario (E) does not require an actual AI service outage;
  the deterministic fallback path is always available and is exercised by design.
  A live Orchestrate unavailability simulation test is deferred to Gate 24's
  full end-to-end smoke run.
- The `format:check` step reports pre-existing formatting issues in `src/api.ts`,
  `src/App.tsx`, and `src/test/App.test.tsx` that predated Gate 23. These are
  unchanged by this gate.
