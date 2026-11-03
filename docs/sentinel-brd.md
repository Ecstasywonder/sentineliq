# SentinelIQ — Business Requirements Document (BRD)

**Document ID:** SNTL-BRD-001  
**Version:** 1.0  
**Date:** 2026-11-03  
**Status:** Approved  
**Author:** IBM Bob (Principal Architect)  
**Reviewers:** Project Owner

---

## 1. Executive Summary

SentinelIQ is a supervised AI security decision-intelligence platform. It receives security events from detection systems, correlates them with operational context, and produces transparent evidence-backed recommendations for human security operators to act upon.

SentinelIQ does not replace security officers. It makes them faster and better informed.

**Core transformation:**

```
Detected Event → Contextual Reasoning → Transparent Recommendation → Human Decision
```

---

## 2. Problem Statement

Security monitoring operators face a persistent operational challenge:

- Detection systems generate high volumes of alerts
- Many alerts lack sufficient context to evaluate quickly
- Context is spread across disconnected systems (access control, scheduling, HR, facility management)
- Time pressure leads to alert fatigue and missed escalations
- Inconsistent decisions reduce auditability and accountability
- No single system synthesises evidence into a clear decision package

SentinelIQ solves this by acting as an AI-powered context broker and decision-support layer between the detection system and the operator.

---

## 3. Product Vision

> **A context-aware, evidence-backed, human-supervised security decision-intelligence system.**

SentinelIQ will make security operators better informed and faster at interpreting events. It must not replace their judgment.

---

## 4. Scope

### 4.1 In Scope

- Security event ingestion and normalisation
- Contextual evidence retrieval (access control, schedules, policies, work orders, deliveries, incident history)
- Deterministic risk assessment with configurable rules
- Confidence assessment separate from risk
- Evidence-backed natural-language explanation
- Supervised human-review workflow
- Operator dashboard
- Audit trail for every decision
- Role-based access control
- Integration health monitoring
- Agent evaluation framework
- MVP simulator for testing

### 4.2 Out of Scope (Permanent)

- Facial recognition or biometric identification
- Autonomous physical security enforcement (door locking, alarms, detention)
- Autonomous police or emergency dispatch
- Automated criminality classification
- Video analytics or VMS detection (consumed as events, not generated)
- Real-time video streaming in the dashboard

### 4.3 Out of Scope (MVP — deferred to production gates)

- Live CCTV/VMS integration
- Real enterprise access-control system integration
- Real workforce scheduling system integration
- SSO/OIDC enterprise identity
- Multi-site tenancy
- Production secret vault integration
- Mobile application

---

## 5. Stakeholders and User Roles

### 5.1 Primary User — Security Monitoring Officer

**Persona: Musa / Maya** *(from SentinelIQ Solution Design PDF)*

Musa/Maya works a shift in a control-room environment, monitors several feeds, and must decide quickly whether an event should be escalated. They understand security procedures but may not have time to search across logs, schedules, and incident history while monitoring live feeds.

**Goals & motivations:** Protect people and assets · Avoid missing events · Report clearly and quickly

**Pain points:** Alert fatigue · Ambiguous events · Slow verification · Poor audit trail

**Must-have experience:** A concise alert with risk level, supporting evidence, recommended next step, and clear human-review controls.

**Success measure:** The user can explain why an alert matters and decide what to do next in less time.

**Context:** Monitors multiple event feeds under time pressure. Needs concise, reliable context to determine whether an event requires action.

**Needs:**
- Fast event triage
- Clear risk and confidence indicators
- Evidence visible without switching systems
- Simple decision controls
- Confidence that recommendations are grounded

**Permissions:**
- View event queue
- Inspect event detail and evidence
- Review AI recommendation
- Accept / reject / dismiss events
- Request additional context
- Escalate events
- Provide feedback

### 5.2 Shift Supervisor

**Context:** Oversees monitoring team. Reviews escalated events. May override decisions within policy.

**Permissions:** All officer permissions, plus:
- Review escalated events
- Override certain decisions (with required rationale)
- Approve high-severity escalations where configured
- Inspect override history

### 5.3 Response Team

**Context:** Receives approved escalation notifications.

**Permissions:**
- Receive escalation information
- Acknowledge response requests

### 5.4 Facility Manager

**Context:** Maintains facility operational data.

**Permissions:**
- Maintain operating schedules
- Maintain zone rules and facility context
- Maintain work orders and planned activities

### 5.5 Security Administrator

**Context:** Configures the platform.

**Permissions:**
- Configure integrations
- Manage facility and location metadata
- Manage risk policies and thresholds
- Configure tool availability and agent settings

### 5.6 Compliance / Audit Reviewer

**Context:** Reviews decision history for compliance and quality assurance.

**Permissions:** Read-only access to:
- Historical decisions and evidence
- Agent recommendations
- Operator actions and audit trail

### 5.7 Platform / System Administrator

**Context:** Responsible for system health.

**Permissions:**
- User management
- RBAC administration
- Deployment and system configuration
- Observability and integration health

### 5.8 AI / Agent Administrator

**Context:** Responsible for agent quality and governance.

**Permissions:**
- Agent versions and evaluation
- Prompt and instruction management
- Model configuration
- Tool permissions
- Performance monitoring

---

## 6. Use Cases

### UC-01 — Security-Event Intake
**Actor:** Detection system, Event simulator  
**Description:** Receive normalised security events via API.  
**Success:** Event is persisted with unique ID, status RECEIVED, timestamp, and source metadata.

### UC-02 — Event Normalisation
**Actor:** System  
**Description:** Convert provider-specific event format to the SentinelIQ event schema.  
**Success:** All required fields are populated; invalid events are rejected with structured error.

### UC-03 — Event Triage
**Actor:** Triage Agent  
**Description:** Classify the event, identify urgency signals, and determine required evidence sources.  
**Success:** Structured triage output with category, urgency signals, and required context list.

### UC-04 — Badge / Access Verification
**Actor:** Context Agent, access-control tool  
**Description:** Query access-control records for the event location within the configured time window.  
**Success:** Access status returned with match/no-match result and evidence IDs.

### UC-05 — Schedule Verification
**Actor:** Context Agent, schedule tool  
**Description:** Determine whether activity at the location and time is scheduled.  
**Success:** Schedule status returned with expected/unexpected classification and evidence IDs.

### UC-06 — Restricted-Area Verification
**Actor:** Context Agent, location-policy tool  
**Description:** Determine whether the location is restricted at the event time.  
**Success:** Policy status, restriction details, and evidence IDs returned.

### UC-07 — Incident-History Retrieval
**Actor:** Context Agent, incident-history tool  
**Description:** Retrieve relevant historical incidents for the location and event type.  
**Success:** Similar incidents returned with metadata and evidence IDs; semantic search used for narrative matching.

### UC-08 — Policy Retrieval
**Actor:** Context Agent, location-policy tool  
**Description:** Retrieve applicable security policy and SOP text.  
**Success:** Relevant policy sections returned with provenance and evidence IDs.

### UC-09 — Evidence Aggregation
**Actor:** Coordinator  
**Description:** Combine all retrieved context into a normalised evidence package.  
**Success:** All sources present with status (verified / unavailable / stale); missing sources explicitly listed.

### UC-10 — Risk Assessment
**Actor:** Risk Engine  
**Description:** Compute a deterministic, policy-driven risk score and level.  
**Success:** Score, level, contributing factors, and policy version returned. Score is reproducible given identical inputs.

### UC-11 — Confidence Assessment
**Actor:** Confidence Engine  
**Description:** Assess evidence completeness separately from risk.  
**Success:** Confidence score, level, and reduction reasons returned. Unavailable sources reduce confidence, not risk.

### UC-12 — Explanation Generation
**Actor:** Explanation Agent  
**Description:** Generate operator-readable explanation grounded only in retrieved evidence.  
**Success:** Summary, why list with evidence IDs, missing evidence, limitations, and recommended action.

### UC-13 — Recommendation Generation
**Actor:** Coordinator  
**Description:** Produce a supervised recommendation for human action.  
**Success:** Recommendation with rationale, evidence references, and required human review flag.

### UC-14 — Alert Prioritisation
**Actor:** System  
**Description:** Order the event queue by risk level, confidence, and time-sensitivity.  
**Success:** CRITICAL and HIGH events appear before LOW; time-sensitive events surfaced prominently.

### UC-15 — Human Review
**Actor:** Security Monitoring Officer  
**Description:** Operator reviews event, evidence, and recommendation.  
**Success:** All evidence, risk, confidence, explanation, and recommendation visible in one interface.

### UC-16 — Human Decision
**Actor:** Security Monitoring Officer  
**Description:** Operator makes a final decision.  
**Options:** Accept recommendation / Reject recommendation / Dismiss / Request more context / Escalate / Override / Add comment.  
**Success:** Decision recorded with user ID, timestamp, role, rationale, and prior state.

### UC-17 — Escalation
**Actor:** Shift Supervisor / Security Monitoring Officer  
**Description:** Route approved incident to response team.  
**Success:** Escalation record includes who approved, what evidence was visible, recommendation made, destination, and timestamp.

### UC-18 — Audit Trail
**Actor:** System  
**Description:** Preserve the complete decision history for every event.  
**Success:** Full reconstruction of event → evidence → risk → explanation → recommendation → human decision → escalation.

### UC-19 — Operator Feedback
**Actor:** Security Monitoring Officer  
**Description:** Record feedback on recommendation quality.  
**Success:** Feedback stored with event ID, operator ID, rating, and free-text comment.

### UC-20 — Post-Incident Review
**Actor:** Compliance / Audit Reviewer  
**Description:** Reconstruct a historical event's full decision path.  
**Success:** All 23 audit fields recoverable (see Section 10).

### UC-21 — Administration
**Actor:** Security Administrator  
**Description:** Manage policies, schedules, locations, integrations, and thresholds.

### UC-22 — Integration Health Monitoring
**Actor:** Platform Administrator, Security Monitoring Officer  
**Description:** Show whether evidence sources are healthy, unavailable, stale, or degraded.

### UC-23 — Agent Evaluation
**Actor:** AI / Agent Administrator  
**Description:** Measure agent behaviour against evaluation datasets.

---

## 7. Functional Requirements

### FR-01 Event Ingestion
- The system SHALL accept security events via a REST API endpoint
- Events SHALL be assigned a unique SentinelIQ event ID
- Duplicate provider events within the deduplication window SHALL be detected and handled
- Events SHALL be validated against the event schema before persistence

### FR-02 Event Processing
- Events SHALL progress through a defined lifecycle: RECEIVED → NORMALISED → ASSESSING → AWAITING_REVIEW → (DISMISSED | ESCALATED | CLOSED | FAILED | CONTEXT_INCOMPLETE)
- Invalid state transitions SHALL be rejected
- Event processing SHALL be resilient to tool or agent failures

### FR-03 Evidence Retrieval
- The system SHALL query all required evidence sources identified by the Triage Agent
- Source unavailability SHALL be recorded as a distinct status (not as absence of evidence)
- Each piece of evidence SHALL carry a unique evidence ID, source, retrieval timestamp, and status

### FR-04 Risk Assessment
- Risk scoring SHALL be deterministic and policy-driven
- The active risk policy version SHALL be recorded with every assessment
- Risk factors SHALL be individually traced to evidence
- Risk and confidence SHALL be modelled and stored independently

### FR-05 Explanation
- Every explanation SHALL be grounded in retrieved evidence
- Evidence IDs SHALL be cited for every factual claim
- Missing evidence SHALL be explicitly listed
- The explanation SHALL use neutral event terminology
- The explanation SHALL NOT invent facts not present in evidence

### FR-06 Human Review
- Every actionable recommendation SHALL require human review before action
- The system SHALL NOT autonomously escalate, lock doors, or notify emergency services
- Human decisions SHALL be captured with full provenance

### FR-07 Audit
- Every event SHALL have a complete, immutable audit record
- Audit records SHALL be accessible to authorised reviewers
- Sensitive tool payloads SHALL be appropriately redacted in audit logs

### FR-08 RBAC
- All API endpoints SHALL enforce role-based access control
- Roles SHALL be assigned least-privilege permissions
- Unauthorised requests SHALL return HTTP 403, not expose system detail

---

## 8. Non-Functional Requirements

### NFR-01 Performance
- Event assessment SHALL complete within 30 seconds under normal load (MVP)
- The operator dashboard SHALL load the event queue within 2 seconds
- API responses SHALL return within 500ms for non-agent endpoints

### NFR-02 Availability
- The MVP system SHALL target 99% availability during demonstration and testing
- The application SHALL remain accessible for manual review even when the AI layer is unavailable

### NFR-03 Security
- All API endpoints SHALL require authentication
- Secrets SHALL never appear in source code, logs, or frontend bundles
- SQL injection SHALL be prevented via parameterised queries / ORM
- XSS SHALL be prevented via output encoding
- All inputs SHALL be validated with explicit schemas

### NFR-04 Auditability
- Every security-relevant action SHALL generate an immutable audit event
- Audit records SHALL be retained for a minimum of 90 days (MVP default)

### NFR-05 Explainability
- Every recommendation SHALL be answerable: "Why did SentinelIQ make this recommendation?"
- Risk factors, evidence references, missing evidence, and confidence effects SHALL all be accessible

### NFR-06 Neutral Language
- The system SHALL use neutral event terminology
- Labels such as "criminal", "intruder", "attacker" SHALL NOT be generated by the AI layer
- Preferred language: "unverified activity", "access status unavailable", "activity inconsistent with schedule"

### NFR-07 Extensibility
- Evidence source integrations SHALL use adapter interfaces replaceable without changing agent contracts
- Risk policy SHALL be configurable without code changes
- Model selection SHALL be configurable without code changes

### NFR-08 Testability
- All business logic SHALL have unit tests
- All API endpoints SHALL have integration tests
- Agent behaviour SHALL have evaluation datasets
- Failure paths SHALL be explicitly tested

---

## 9. Critical Distinction: Risk vs. Confidence

These MUST be modelled independently throughout:

| Scenario | Risk | Confidence | Meaning |
|----------|------|-----------|---------|
| After-hours restricted area, all sources healthy | HIGH | HIGH | Evidence strongly supports concern |
| After-hours restricted area, badge system down | HIGH | LOW | Serious indicators present but key evidence missing |
| Authorised maintenance, all sources confirm | LOW | HIGH | Evidence strongly supports normal activity |
| Routine arrival, schedule unavailable | LOW | LOW | Looks routine but cannot be fully verified |

**Missing data is NEVER negative evidence.**  
Unavailable sources reduce confidence only. They do not increase risk.

---

## 10. Audit Record Requirements

Each event audit record MUST preserve:

1. Original event payload
2. Normalised event data
3. Agent version invoked
4. Risk policy version
5. Tools invoked (names and sequence)
6. Tool inputs (where safe to log)
7. Tool result references (evidence IDs)
8. Evidence collected (full set)
9. Evidence source for each item
10. Evidence retrieval timestamps
11. Missing / unavailable sources
12. Risk factors applied
13. Risk score and level
14. Confidence score and level
15. Explanation text generated
16. Recommendation generated
17. Model metadata (where available)
18. Human reviewer identity
19. Human decision
20. Override reason (if applicable)
21. Escalation destination and timestamp (if applicable)
22. Operator feedback (if provided)
23. Final outcome / closure reason

---

## 11. Required Demo Scenarios (MVP)

### Scenario A — Authorised Activity
- Valid badge, scheduled activity, policy permits
- Expected: LOW risk, HIGH confidence, operator can dismiss/confirm

### Scenario B — Unverified After-Hours Event
- After permitted hours, restricted area, no badge, no schedule, prior incident
- Expected: HIGH/CRITICAL risk, HIGH confidence (sources healthy), human review required

### Scenario C — Missing Evidence
- Badge service unavailable, schedule service unavailable
- Expected: Sources marked unavailable, confidence reduced, NO "no badge exists" statement

### Scenario D — Conflicting Evidence
- Valid badge exists; schedule says unexpected; policy restricts area
- Expected: Conflict shown explicitly, confidence reduced, human review required

### Scenario E — AI Unavailable
- Expected: Event remains accessible, deterministic evidence shown, AI explanation marked unavailable

---

## 12. Success Metrics

| Metric | Target |
|--------|--------|
| Event-review time | Measurably reduced vs. manual lookup |
| Recommendation acceptance rate | Tracked per operator |
| False escalation rate | Tracked and minimised |
| Override rate | Tracked with reasons |
| Missing-context rate | Tracked per source |
| Tool failure rate | < 1% under normal operation |
| Assessment latency | < 30s (MVP) |
| Explanation usefulness | Operator-rated; target positive majority |

---

## 13. Acceptance Criteria — MVP Complete

- [ ] Event enters system and is normalised
- [ ] Evidence is gathered from all configured sources
- [ ] Risk is deterministically calculated and traceable
- [ ] Confidence is separately calculated
- [ ] Explanation is grounded in evidence with citations
- [ ] Missing evidence is explicitly stated
- [ ] Recommendation is generated
- [ ] Operator can accept / reject / dismiss / escalate / request context
- [ ] All decisions are audited with full provenance
- [ ] Agents can be traced and evaluated
- [ ] All five demo scenarios work correctly
- [ ] Relevant tests pass
- [ ] Critical failure states degrade safely
- [ ] No autonomous enforcement exists anywhere

---

## 14. Document History

| Version | Date | Author | Change |
|---------|------|--------|--------|
| 1.0 | 2026-11-03 | IBM Bob | Initial BRD — Gate 1 |
