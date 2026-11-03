# SentinelIQ — System Architecture

**Document ID:** SNTL-ARCH-001  
**Version:** 1.0  
**Date:** 2026-11-03  
**Status:** Approved  
**Author:** IBM Bob (Principal Architect)

---

## 1. Architecture Principles

1. **Human authority is non-negotiable** — no autonomous enforcement at any layer
2. **Risk ≠ Confidence** — independently modelled, never merged
3. **Missing evidence ≠ negative evidence** — source unavailability reduces confidence only
4. **Deterministic risk** — the numerical score is never a hidden LLM judgment
5. **Evidence-grounded explanation** — agents may only use supplied evidence
6. **Least privilege** — each agent and tool has only the permissions it needs
7. **Auditability by design** — every action is traceable
8. **Adapter isolation** — evidence source integrations are replaceable without changing agent contracts

---

## 2. System Context

```
┌─────────────────────────────────────────────────────────────────┐
│                    External Systems                              │
│                                                                  │
│   ┌──────────────────┐    ┌──────────────────────────────────┐  │
│   │  Detection System │    │  Enterprise Context Sources      │  │
│   │  (CCTV/VMS/Sim)  │    │  Access Control | Schedules      │  │
│   └────────┬─────────┘    │  Work Orders | Visitor Mgmt      │  │
│            │              │  Facility Policies | History      │  │
│            │              └──────────────┬───────────────────┘  │
└────────────┼─────────────────────────────┼─────────────────────┘
             │                             │
             ▼                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                       SentinelIQ Platform                       │
│                                                                  │
│   Event Ingestion API ◄──────────────────────────────────────  │
│           │                                                      │
│           ▼                                                      │
│   Normalise + Validate + Persist                                 │
│           │                                                      │
│           ▼                                                      │
│   ┌───────────────────┐     ┌─────────────────────────────────┐ │
│   │ watsonx Orchestrate│     │  SentinelIQ Backend             │ │
│   │ Agent Runtime      │◄───►│  Domain | APIs | State          │ │
│   │                   │     │  Risk Engine | Confidence        │ │
│   │  Coordinator       │     │  Audit Trail | RBAC             │ │
│   │  Triage Agent      │     └─────────────────────────────────┘ │
│   │  Context Agent     │                   │                     │
│   │  Explanation Agent │                   ▼                     │
│   └───────────────────┘     ┌─────────────────────────────────┐ │
│                             │  Operator Dashboard (React)     │ │
│                             │  Event Queue | Decision Controls│ │
│                             │  Evidence Panel | Audit Trail   │ │
│                             └─────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
             │
             ▼
    Authorised Human Decision
             │
             ▼
    Approved Response Action (human-initiated only)
```

---

## 3. Logical Architecture — Event Assessment Flow

```
Detection System / Simulator
            │
            │  POST /api/v1/events
            ▼
    ┌───────────────────┐
    │  Event Ingestion  │  Validate → Normalise → Deduplicate → Persist
    │  Adapter          │  Status: RECEIVED → NORMALISED
    └────────┬──────────┘
             │
             │  Trigger assessment
             ▼
    ┌───────────────────────────────────────────────────────┐
    │              Sentinel Coordinator                      │
    │  (watsonx Orchestrate — orchestration component)      │
    └────────┬──────────────────────────────────────────────┘
             │
             │  1. Invoke Triage
             ▼
    ┌───────────────────┐
    │   Triage Agent    │  Classify event → identify urgency signals
    │                   │  → determine required context sources
    └────────┬──────────┘
             │  Triage result: category + urgency + required_context[]
             │
             │  2. Invoke Context Retrieval
             ▼
    ┌───────────────────────────────────────────────────────┐
    │              Context Agent                             │
    └───┬───────────────┬────────────────┬──────────────────┘
        │               │                │
        ▼               ▼                ▼
  get_access_events  get_schedule    get_location_policy
  get_camera_meta    get_work_orders get_delivery_context
  search_incident_history           get_visitor_context
  get_integration_health
        │               │                │
        └───────────────┴────────────────┘
                        │
                        │  Normalised evidence package
                        ▼
    ┌───────────────────────────────────────────────────────┐
    │         Evidence Aggregation + Validation              │
    │  All sources → status (verified/unavailable/stale)     │
    │  Missing sources → explicit list                       │
    └────────┬──────────────────────────────────────────────┘
             │
             │  3. Deterministic Risk Assessment
             ▼
    ┌───────────────────┐
    │   Risk Engine     │  Policy-driven scoring
    │   (deterministic) │  Versioned factors + weights
    └────────┬──────────┘  Traceable factor contributions
             │
             │  4. Confidence Assessment
             ▼
    ┌───────────────────┐
    │ Confidence Engine │  Source availability weighting
    │   (deterministic) │  Conflict detection
    └────────┬──────────┘  Freshness assessment
             │
             │  5. Explanation Generation
             ▼
    ┌───────────────────┐
    │ Explanation Agent │  Evidence-grounded narrative
    │                   │  Neutral language
    └────────┬──────────┘  Evidence citations required
             │
             │  6. Persist assessment + initiate human review
             ▼
    ┌───────────────────┐
    │  Human Review     │  Status: AWAITING_REVIEW
    │  Workflow         │  All decision options available
    └────────┬──────────┘
             │
             ▼
    ┌─────────────────────────────────────────────────────────┐
    │              Operator Dashboard                          │
    │                                                          │
    │  Accept │ Reject │ Dismiss │ More Context │ Escalate    │
    └────────────────────────┬────────────────────────────────┘
                             │
                             ▼
                       Audit Trail
                    (immutable record)
```

---

## 4. Component Responsibilities

### 4.1 SentinelIQ Backend (FastAPI)

**Owns:**
- Event persistence and lifecycle management
- Domain entity CRUD (locations, cameras, schedules, policies, incidents)
- Deterministic Risk Engine
- Confidence Engine
- Evidence aggregation and storage
- Human review workflow state
- Audit trail generation and storage
- RBAC enforcement
- API contract for frontend and integrations
- Integration health monitoring
- Orchestrate tool endpoint hosting (where tools are implemented as API-backed services)

**Does NOT own:**
- Agent orchestration logic (watsonx Orchestrate handles that)
- LLM inference (Orchestrate handles that)
- Agent prompt management (Orchestrate handles that)

### 4.2 watsonx Orchestrate (Agent Runtime)

**Owns:**
- Agent execution (Triage, Context, Explanation, Coordinator)
- Tool invocation and routing
- Agent-to-agent collaboration
- Workflow state within the assessment session
- Model routing and selection
- Agent evaluation
- Agent tracing and observability
- Agent version management
- Tool permissions

**Does NOT own:**
- Application domain state (stored in SentinelIQ backend/DB)
- Human review workflow (SentinelIQ backend owns this)
- Audit trail (SentinelIQ backend owns this)
- User authentication (SentinelIQ backend owns this)

### 4.3 Triage Agent

- Input: normalised event
- Output: category, urgency signals, required context list
- MUST NOT: determine guilt, perform enforcement, invent identities

### 4.4 Context Agent

- Input: event + required context list from triage
- Invokes: access, schedule, policy, incident history, work orders, delivery, visitor, camera metadata, integration health tools
- Output: normalised evidence package (all sources with status)
- Tools are READ-ONLY

### 4.5 Explanation Agent

- Input: evidence package + risk assessment + confidence assessment
- Output: structured explanation with evidence citations
- MUST NOT: use information not in the supplied evidence package
- MUST use neutral terminology

### 4.6 Sentinel Coordinator

- Orchestrates the full assessment pipeline
- Does NOT invent evidence
- Persists assessment state via SentinelIQ backend API
- Initiates human review state

### 4.7 Operator Dashboard (React)

- Consumes SentinelIQ backend API
- Renders event queue, event detail, evidence panel, decision controls, audit trail
- Clearly distinguishes AI Recommendation from Human Decision (never merged)
- Accessible: not colour-only risk communication, keyboard navigable

---

## 5. Data Flow — Evidence Package

```
Context Agent
    │
    ├── get_access_events(location, time_window)
    │       └── AccessControlAdapter → mock/real
    │
    ├── get_schedule_context(location, timestamp)
    │       └── ScheduleAdapter → mock/real
    │
    ├── get_location_policy(location_id)
    │       └── PolicyAdapter → DB / document store
    │
    ├── search_incident_history(location, event_type, timestamp)
    │       └── IncidentHistoryAdapter → DB + pgvector
    │
    ├── get_active_work_orders(location, timestamp)
    │       └── WorkOrderAdapter → mock/real
    │
    ├── get_delivery_context(location, timestamp)
    │       └── DeliveryAdapter → mock/real
    │
    ├── get_camera_metadata(camera_id)
    │       └── CameraRepository → DB
    │
    └── get_integration_health()
            └── IntegrationHealthService → DB

All results → EvidenceAggregator
    │
    ├── Evidence items with IDs, source, timestamp, status
    ├── Missing sources explicitly listed
    └── Staleness flags where applicable
```

---

## 6. Risk Engine — Scoring Model

Risk scoring is deterministic. The LLM never directly produces a risk score.

### Default Risk Factors (v1.0 policy)

| Factor | Weight | Direction |
|--------|--------|-----------|
| No matching authorised badge | +25 | increases risk |
| Activity outside permitted schedule | +20 | increases risk |
| Restricted location at event time | +25 | increases risk |
| No approved work order | +15 | increases risk |
| Relevant recent incidents (≥1) | +10 | increases risk |
| Forced-door / security alarm | +40 | increases risk |
| Known approved maintenance | −30 | decreases risk |
| Valid access + matching schedule | −35 | decreases risk |

### Default Thresholds (v1.0 policy)

| Score Range | Level |
|-------------|-------|
| 0–24 | LOW |
| 25–49 | MEDIUM |
| 50–74 | HIGH |
| 75+ | CRITICAL |

All thresholds and weights are stored in the `risk_policies` and `risk_policy_factors` tables. No hard-coding in application logic.

---

## 7. Confidence Engine — Model

Confidence is computed separately from risk.

### Confidence Reduction Factors

| Factor | Reduction |
|--------|-----------|
| Required source unavailable | −20 per source |
| Source response stale (>configured age) | −10 per source |
| Contradictory evidence detected | −15 |
| Incomplete event metadata | −10 |
| Tool retrieval error | −10 |
| LLM assessment unavailable | −20 |

Confidence cannot go below 0.0 or above 1.0.

### Confidence Levels

| Score | Level |
|-------|-------|
| 0.8–1.0 | HIGH |
| 0.5–0.79 | MEDIUM |
| 0.0–0.49 | LOW |

---

## 8. Event Lifecycle

```
RECEIVED
    │
    ▼
NORMALISED
    │
    ▼
ASSESSING ──────────────────────────────────┐
    │                                        │ (failure)
    ▼                                        ▼
AWAITING_REVIEW              CONTEXT_INCOMPLETE / FAILED
    │
    ├──── Human: Dismiss ──────────────► DISMISSED
    │
    ├──── Human: Accept/Reject ────────► CLOSED
    │
    └──── Human: Escalate ─────────────► ESCALATED ──► CLOSED
```

Valid transitions are enforced at the application layer. Invalid transitions are rejected with a structured error.

---

## 9. Security Architecture

### Authentication
- JWT-based for MVP (Bearer token)
- Tokens issued on login, short-lived (60 min default), refresh token support
- Production target: SSO/OIDC via enterprise IdP (Gate 34)

### Authorisation
- RBAC with roles: `officer`, `supervisor`, `response_team`, `facility_manager`, `security_admin`, `audit_reviewer`, `platform_admin`, `agent_admin`
- Permissions checked at API route level
- Least-privilege: Triage Agent has no escalation tools; Context Agent has read-only tools

### Secrets
- MVP: environment variables, never in source
- Production: secrets manager (Gate 35)

### Transport
- TLS assumed at load balancer/proxy level in production
- Local development: HTTP acceptable (EC2 dev environment)

### Input Validation
- All API inputs validated via Pydantic schemas
- Agent inputs validated before tool invocation
- Agent outputs validated against schemas before use

### Prompt Injection Defence
- Retrieved documents are treated as untrusted data, not system instructions
- Evidence is passed to agents as structured data, not raw text prepended to prompts
- Adversarial cases tested in evaluation dataset

---

## 10. Integration Architecture

### Adapter Pattern

All external integrations use the adapter pattern:

```
SentinelIQ Domain Interface
    │
    ├── AccessControlAdapter
    │       ├── MockAccessControlAdapter (MVP)
    │       └── EnterpriseAccessControlAdapter (production)
    │
    ├── ScheduleAdapter
    │       ├── MockScheduleAdapter (MVP)
    │       └── EnterpriseScheduleAdapter (production)
    │
    ├── WorkOrderAdapter
    │       ├── MockWorkOrderAdapter (MVP)
    │       └── EnterpriseWorkOrderAdapter (production)
    │
    └── EventSourceAdapter
            ├── SimulatorAdapter (MVP)
            └── VMSAdapter (production)
```

Adapter interfaces are defined as Python abstract base classes. Tool schemas reference the interface contract, not a specific implementation.

---

## 11. Deployment Architecture (MVP)

```
EC2 Instance (Ubuntu)
    │
    └── Docker Compose
            │
            ├── backend     (FastAPI — port 8000)
            ├── frontend    (Vite/React served — port 3000)
            ├── postgres    (PostgreSQL 15 + pgvector — port 5432 internal)
            └── (future: redis for queue/caching)
```

---

## 12. Document History

| Version | Date | Author | Change |
|---------|------|--------|--------|
| 1.0 | 2026-11-03 | IBM Bob | Initial architecture — Gate 1 |
