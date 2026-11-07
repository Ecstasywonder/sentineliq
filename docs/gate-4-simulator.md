# Gate 4 — Security-event simulator

The checked-in dataset at `data/scenarios/mvp-scenarios.json` contains nineteen deterministic security-event fixtures. It covers every scenario class required by the master build prompt, including the five primary demo conditions: authorized activity, unverified after-hours activity, missing data, conflicting data, and AI-unavailable-compatible deterministic input.

Use `POST /api/v1/simulator/generate` with an authenticated principal holding `events:ingest`:

```json
{"scenario_ids":["forced-door-alarm"],"persist":false}
```

Omit `scenario_ids` to select all scenarios. `persist:false` returns a stable preview. Persisted events retain fixed provider IDs; rerunning within the configured deduplication window returns the original event and marks it as a duplicate, which makes demonstrations repeatable without uncontrolled event creation.

Dataset validation rejects malformed, empty, or duplicate scenario IDs and ensures every fixture has the required ingestion fields. Focused tests cover dataset coverage, unknown IDs, repository operation, preview, persistence, and idempotency.
