# Gate 7 — Evidence Retrieval API (Context Tools)

**Document ID:** SNTL-GATE-007  
**Status:** ✅ Complete  
**Date:** 2026-11-03  
**Tests Added:** ~50 (tools API + evidence aggregator)  
**Cumulative Tests:** ~194  

---

## Scope

Gate 7 delivers the seven read-only context-tool endpoints and the underlying
adapter layer that the watsonx Orchestrate agents will call at assessment time.
All tools are read-only (ADR-005) and require the `tools:read` permission.

---

## Files Produced

| File | Purpose |
|------|---------|
| `app/integrations/__init__.py` | Package marker |
| `app/integrations/base.py` | Abstract base classes (`BaseAdapter`, `AccessControlAdapter`, `ScheduleAdapter`, `WorkOrderAdapter`, `DeliveryAdapter`) |
| `app/integrations/access_control.py` | `MockAccessControlAdapter` — reads `access_events` table |
| `app/integrations/schedule.py` | `MockScheduleAdapter` — reads `schedules` table |
| `app/integrations/work_order.py` | `MockWorkOrderAdapter` — reads `work_orders` table |
| `app/integrations/delivery.py` | `MockDeliveryAdapter` — reads `deliveries` table |
| `app/services/evidence_aggregator.py` | `EvidenceAggregator` — error-isolated gather of all 7 sources |
| `app/schemas/tools.py` | Pydantic response schemas + `AggregatedEvidence` preview |
| `app/api/v1/endpoints/tools.py` | 7 FastAPI route handlers |
| `tests/test_tools_api.py` | Integration tests for all 7 endpoints |
| `tests/test_evidence_aggregator.py` | Unit tests for `EvidenceAggregator` |

**Modified:**
- `app/api/v1/router.py` — mounts `/tools` router
- `app/security/rbac.py` — adds `tools:read` to all 8 roles
- `backend/pyproject.toml` — adds `aiosqlite>=0.20.0` to dev deps
- `tests/test_auth.py` — ruff I001 import-sort fix
- `docs/master-gate-plan.md` — Gate 7 complete, Gate 8 next

---

## API Surface

All routes: `GET /api/v1/tools/<resource>`  
All require: `Authorization: Bearer <token>` with `tools:read` permission.  
All responses: `{ meta: ToolMeta, records: [...] }`

| Endpoint | Query Params | Source Table |
|----------|-------------|-------------|
| `GET /access-events` | `location_id` *(required)*, `facility_id`, `limit` | `access_events` |
| `GET /schedule` | `location_id`, `facility_id`, `schedule_type`, `limit` | `schedules` |
| `GET /work-orders` | `location_id` *(required)*, `facility_id`, `status`, `limit` | `work_orders` |
| `GET /delivery` | `location_id` *(required)*, `facility_id`, `limit` | `deliveries` |
| `GET /location-policy` | `location_id` *(required)*, `facility_id` | `security_rules` |
| `GET /incident-history` | `location_id` *(required)*, `facility_id`, `limit` | `incident_history` |
| `GET /integration-health` | *(none)* | 4 adapter probes + `integration_health` |

---

## Adapter Architecture (ADR-005)

```
BaseAdapter (ABC)
 ├── AccessControlAdapter (ABC)  →  MockAccessControlAdapter
 ├── ScheduleAdapter      (ABC)  →  MockScheduleAdapter
 ├── WorkOrderAdapter     (ABC)  →  MockWorkOrderAdapter
 └── DeliveryAdapter      (ABC)  →  MockDeliveryAdapter
```

Each mock adapter:
- Accepts an `AsyncSession` at construction
- Reads from the corresponding ORM table
- Exposes `async health_check() -> dict` that probes the DB and returns latency
- Returns `list[dict]` which the endpoint/aggregator maps to Pydantic records

In production, swap a mock with a real adapter by implementing the same abstract
class — no endpoint code changes required.

---

## EvidenceAggregator

`app/services/evidence_aggregator.py` — `EvidenceAggregator.gather(event_id, location_id, ...)`:

- Calls all 7 evidence sources in sequence
- Each call is wrapped in `_safe()` — any exception is caught, logged, and
  stored in `AggregatedEvidence.errors` rather than raised
- Returns a fully-typed `AggregatedEvidence` object with optional sections
- The `ConfidenceEngine` will reduce confidence for any `None` section (ADR-004)

---

## ToolMeta

Every response includes:

```json
{
  "meta": {
    "source": "mock_access_control",
    "record_count": 3,
    "truncated": false
  },
  "records": [...]
}
```

`truncated: true` when `len(records) == limit` — signals the agent to refine
its query if needed.

---

## Permission Model Update

`tools:read` added to all 8 roles in `app/security/rbac.py`:

| Role | tools:read |
|------|-----------|
| officer | ✅ |
| supervisor | ✅ |
| response_team | ✅ |
| facility_manager | ✅ |
| security_admin | ✅ |
| audit_reviewer | ✅ |
| platform_admin | ✅ |
| agent_admin | ✅ |

---

## ADR Compliance

| ADR | Rule | Enforced |
|-----|------|---------|
| ADR-003 | LLM never produces risk score | ✅ No LLM calls in any adapter |
| ADR-004 | Missing evidence → confidence reduction only | ✅ `errors` dict → `ConfidenceEngine.SOURCE_UNAVAILABLE` path |
| ADR-005 | Adapters are replaceable | ✅ Abstract base classes, mock + real swap requires no endpoint change |
| ADR-006 | Human review non-bypassable | ✅ Not applicable to read-only tools |

---

## EC2 Deploy Commands

```bash
# Local (Git Bash)
git add backend/app/integrations/ \
        backend/app/services/evidence_aggregator.py \
        backend/app/schemas/tools.py \
        backend/app/api/v1/endpoints/tools.py \
        backend/app/api/v1/router.py \
        backend/app/security/rbac.py \
        backend/pyproject.toml \
        backend/tests/test_tools_api.py \
        backend/tests/test_evidence_aggregator.py \
        backend/tests/test_auth.py \
        docs/master-gate-plan.md \
        docs/gate-7-evidence-retrieval.md
git commit -m "feat(gate-7): evidence retrieval API — 7 context tools + EvidenceAggregator"
git push origin main

# EC2
cd ~/sentineliq && git pull
cd backend && source .venv/bin/activate
uv pip install -e ".[dev]"    # picks up aiosqlite
python -m ruff check app/ tests/ --fix
APP_ENV=development SECRET_KEY=test-secret-key \
  DATABASE_URL="sqlite+aiosqlite:///:memory:" \
  DATABASE_URL_SYNC="sqlite:///:memory:" \
  pytest tests/ -v --tb=short
# Expected: ~194 passed, 0 failed
```
