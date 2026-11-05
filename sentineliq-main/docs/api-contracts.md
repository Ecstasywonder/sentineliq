# SentinelIQ — API Contracts

**Document ID:** SNTL-API-001  
**Version:** 1.0  
**Date:** 2026-11-03  
**Status:** Approved  
**Author:** IBM Bob (Principal Architect)

---

## 1. General Conventions

- **Base URL:** `/api/v1`
- **Authentication:** Bearer JWT token in `Authorization` header
- **Content-Type:** `application/json`
- **Timestamps:** ISO 8601 UTC (e.g. `2026-11-03T09:00:00Z`)
- **IDs:** UUID v4 strings
- **Versioning:** URL path versioning (`/api/v1/`, `/api/v2/`)
- **OpenAPI:** Auto-generated at `/docs` (Swagger UI) and `/openapi.json`

### Standard Error Response

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "event_type is required",
    "details": [
      { "field": "event_type", "message": "field required" }
    ],
    "request_id": "req-abc-123"
  }
}
```

### Error Codes

| Code | HTTP Status | Meaning |
|------|------------|---------|
| `VALIDATION_ERROR` | 422 | Schema validation failed |
| `NOT_FOUND` | 404 | Resource does not exist |
| `UNAUTHORIZED` | 401 | No valid token |
| `FORBIDDEN` | 403 | Insufficient role |
| `DUPLICATE_EVENT` | 409 | Idempotency key already exists |
| `SOURCE_UNAVAILABLE` | 503 | Evidence source unreachable |
| `ASSESSMENT_INCOMPLETE` | 202 | Assessment still in progress |
| `AI_UNAVAILABLE` | 503 | Agent runtime unreachable |
| `WORKFLOW_ERROR` | 500 | Unexpected assessment failure |
| `INTERNAL_ERROR` | 500 | Unexpected server error |

---

## 2. Health Endpoints

### GET /health

Liveness check. Returns 200 if the application process is running.

**Response 200:**
```json
{
  "status": "ok",
  "timestamp": "2026-11-03T09:00:00Z"
}
```

### GET /ready

Readiness check. Returns 200 only if the database is reachable and migrations are current.

**Response 200:**
```json
{
  "status": "ready",
  "database": "connected",
  "migrations": "current",
  "timestamp": "2026-11-03T09:00:00Z"
}
```

**Response 503:**
```json
{
  "status": "not_ready",
  "database": "unreachable",
  "timestamp": "2026-11-03T09:00:00Z"
}
```

---

## 3. Events API

### POST /api/v1/events

Submit a security event for assessment.

**Required role:** Any authenticated user (event source API key in production)

**Request body:**
```json
{
  "provider_event_id": "EVT-20481",
  "event_type": "person_detected",
  "timestamp": "2026-11-02T22:41:18Z",
  "camera_id": "CAM-DOCK-03",
  "location_id": "LOADING_DOCK_3",
  "detector_confidence": 0.94,
  "zone": "restricted_after_hours",
  "thumbnail_url": "/media/EVT-20481.jpg",
  "raw_metadata": {}
}
```

**Field rules:**
- `provider_event_id` — string, required, used for deduplication
- `event_type` — enum: `person_detected | door_forced | motion_detected | badge_event | delivery_detected | vehicle_detected | alarm_triggered | other`
- `timestamp` — ISO 8601 UTC, required
- `camera_id` — string, optional
- `location_id` — string, required
- `detector_confidence` — float 0.0–1.0, optional
- `zone` — string, optional
- `thumbnail_url` — string, optional
- `raw_metadata` — object, optional, stored but not used in reasoning

**Response 201 — Created:**
```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "provider_event_id": "EVT-20481",
  "status": "received",
  "created_at": "2026-11-03T09:00:00Z",
  "assessment_url": "/api/v1/events/550e8400-e29b-41d4-a716-446655440000/assessment"
}
```

**Response 409 — Duplicate:**
```json
{
  "error": {
    "code": "DUPLICATE_EVENT",
    "message": "Event with provider_event_id EVT-20481 already received within deduplication window",
    "existing_event_id": "550e8400-e29b-41d4-a716-446655440000"
  }
}
```

---

### GET /api/v1/events

List events. Supports filtering and pagination.

**Required role:** `officer`, `supervisor`, `audit_reviewer`

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `status` | enum | all | Filter by status |
| `risk_level` | enum | all | Filter by risk level |
| `location_id` | string | — | Filter by location |
| `facility_id` | string | — | Filter by facility |
| `from_time` | ISO 8601 | — | Events after this time |
| `to_time` | ISO 8601 | — | Events before this time |
| `page` | int | 1 | Page number |
| `page_size` | int | 20 | Items per page (max 100) |
| `sort_by` | enum | `risk_priority` | `risk_priority \| timestamp \| status` |

**Response 200:**
```json
{
  "events": [
    {
      "event_id": "550e8400-e29b-41d4-a716-446655440000",
      "event_type": "person_detected",
      "timestamp": "2026-11-02T22:41:18Z",
      "location_id": "LOADING_DOCK_3",
      "location_name": "Loading Dock 3",
      "facility_id": "FACILITY-001",
      "status": "awaiting_review",
      "risk_level": "critical",
      "risk_score": 78,
      "confidence_level": "high",
      "confidence_score": 0.89,
      "age_seconds": 145,
      "created_at": "2026-11-03T09:00:00Z"
    }
  ],
  "pagination": {
    "page": 1,
    "page_size": 20,
    "total": 47,
    "total_pages": 3
  }
}
```

---

### GET /api/v1/events/{event_id}

Get full event detail.

**Required role:** `officer`, `supervisor`, `audit_reviewer`

**Response 200:**
```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "provider_event_id": "EVT-20481",
  "event_type": "person_detected",
  "timestamp": "2026-11-02T22:41:18Z",
  "camera_id": "CAM-DOCK-03",
  "location_id": "LOADING_DOCK_3",
  "location_name": "Loading Dock 3",
  "facility_id": "FACILITY-001",
  "detector_confidence": 0.94,
  "zone": "restricted_after_hours",
  "thumbnail_url": "/media/EVT-20481.jpg",
  "status": "awaiting_review",
  "created_at": "2026-11-03T09:00:00Z",
  "updated_at": "2026-11-03T09:00:15Z",
  "assessment": {
    "risk_level": "critical",
    "risk_score": 78,
    "confidence_level": "high",
    "confidence_score": 0.89,
    "summary": "Unverified activity detected at Loading Dock 3 after permitted operating hours.",
    "recommendation": "Review the live camera feed and escalate to the shift supervisor if activity cannot be verified.",
    "assessed_at": "2026-11-03T09:00:12Z"
  }
}
```

---

### GET /api/v1/events/{event_id}/evidence

Get the full evidence package for an event.

**Required role:** `officer`, `supervisor`, `audit_reviewer`

**Response 200:**
```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "evidence_items": [
    {
      "evidence_id": "ACCESS-Q-221",
      "source": "access_control",
      "source_type": "structured",
      "status": "verified",
      "retrieved_at": "2026-11-03T09:00:05Z",
      "relevance": "No authorised badge event found within 10-minute window",
      "content": {
        "matching_access_found": false,
        "time_window_minutes": 10,
        "records_searched": 3
      }
    },
    {
      "evidence_id": "POL-203",
      "source": "location_policy",
      "source_type": "structured",
      "status": "verified",
      "retrieved_at": "2026-11-03T09:00:06Z",
      "relevance": "Location is restricted after 21:00",
      "content": {
        "restricted": true,
        "restriction_start": "21:00",
        "restriction_end": "06:00",
        "policy_reference": "SEC-POL-DOCK-001"
      }
    }
  ],
  "missing_sources": [],
  "evidence_summary": {
    "total": 4,
    "verified": 4,
    "unavailable": 0,
    "stale": 0
  }
}
```

---

### GET /api/v1/events/{event_id}/assessment

Get the full assessment result for an event.

**Required role:** `officer`, `supervisor`, `audit_reviewer`

**Response 200:**
```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "assessment_id": "asm-abc-001",
  "risk_policy_version": "1.0",
  "risk_score": 78,
  "risk_level": "critical",
  "risk_factors": [
    {
      "factor_id": "no_matching_badge",
      "label": "No matching authorised badge",
      "weight": 25,
      "direction": "increases_risk",
      "evidence_ids": ["ACCESS-Q-221"]
    },
    {
      "factor_id": "restricted_area",
      "label": "Restricted location at event time",
      "weight": 25,
      "direction": "increases_risk",
      "evidence_ids": ["POL-203"]
    },
    {
      "factor_id": "outside_schedule",
      "label": "Activity outside permitted schedule",
      "weight": 20,
      "direction": "increases_risk",
      "evidence_ids": ["SCH-Q-882"]
    },
    {
      "factor_id": "recent_incidents",
      "label": "Relevant recent incidents",
      "weight": 8,
      "direction": "increases_risk",
      "evidence_ids": ["INC-18", "INC-29"]
    }
  ],
  "confidence_score": 0.89,
  "confidence_level": "high",
  "confidence_reductions": [],
  "explanation": {
    "summary": "Unverified activity was detected at Loading Dock 3 after permitted operating hours.",
    "why": [
      {
        "text": "No matching authorised badge event was found within the configured 10-minute time window.",
        "evidence_ids": ["ACCESS-Q-221"]
      },
      {
        "text": "The location is restricted after 21:00 per facility policy.",
        "evidence_ids": ["POL-203"]
      },
      {
        "text": "No scheduled activity (maintenance, delivery, or shift) was found for this location at this time.",
        "evidence_ids": ["SCH-Q-882"]
      },
      {
        "text": "Two similar events were recorded at this location within the past 30 days.",
        "evidence_ids": ["INC-18", "INC-29"]
      }
    ],
    "missing_evidence": [],
    "limitations": [],
    "recommended_action": "Review the live camera feed and escalate to the shift supervisor if activity cannot be verified."
  },
  "assessed_at": "2026-11-03T09:00:12Z",
  "agent_run_id": "run-xyz-789"
}
```

---

### POST /api/v1/events/{event_id}/request-context

Request additional context retrieval for an event.

**Required role:** `officer`, `supervisor`

**Request body:**
```json
{
  "sources": ["access_control", "visitor_management"],
  "reason": "Initial assessment did not include visitor records"
}
```

**Response 202:**
```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "assessing",
  "message": "Additional context retrieval initiated"
}
```

---

### POST /api/v1/events/{event_id}/decision

Submit a human decision on an event.

**Required role:** `officer`, `supervisor`

**Request body:**
```json
{
  "decision": "escalate",
  "rationale": "No badge found, after-hours, restricted area. Escalating to shift supervisor for review.",
  "recommendation_id": "rec-abc-001",
  "override": false
}
```

**Field rules:**
- `decision` — enum: `accept | reject | dismiss | request_context | escalate | override`
- `rationale` — string, required for `escalate`, `override`, `reject`; optional for `accept`, `dismiss`
- `recommendation_id` — UUID, required
- `override` — boolean, required true if decision = `override`; requires supervisor role

**Response 200:**
```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "decision_id": "dec-abc-001",
  "decision": "escalate",
  "decided_by": "user-001",
  "decided_at": "2026-11-03T09:01:00Z",
  "new_status": "escalated"
}
```

---

### POST /api/v1/events/{event_id}/escalate

Escalate an event to a response destination.

**Required role:** `officer` (with escalation permission), `supervisor`

**Request body:**
```json
{
  "destination": "shift_supervisor",
  "priority": "high",
  "note": "After-hours restricted area activity — immediate review required"
}
```

**Response 201:**
```json
{
  "escalation_id": "esc-abc-001",
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "destination": "shift_supervisor",
  "escalated_by": "user-001",
  "escalated_at": "2026-11-03T09:01:05Z",
  "status": "pending_acknowledgement"
}
```

---

### POST /api/v1/events/{event_id}/feedback

Submit operator feedback on an event assessment.

**Required role:** `officer`, `supervisor`

**Request body:**
```json
{
  "recommendation_useful": true,
  "recommendation_accurate": true,
  "missing_context": "Visitor management records would have been helpful",
  "outcome": "confirmed_incident",
  "notes": "Activity was confirmed as unauthorised access. Escalation was appropriate."
}
```

**Response 201:**
```json
{
  "feedback_id": "fb-abc-001",
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "submitted_at": "2026-11-03T09:05:00Z"
}
```

---

## 4. Audit API

### GET /api/v1/audit/events/{event_id}

Get the full audit trail for an event.

**Required role:** `audit_reviewer`, `supervisor`, `platform_admin`

**Response 200:**
```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "audit_trail": [
    {
      "audit_id": "aud-001",
      "action": "event_received",
      "actor": "system",
      "timestamp": "2026-11-03T09:00:00Z",
      "details": { "provider_event_id": "EVT-20481", "source": "simulator" }
    },
    {
      "audit_id": "aud-002",
      "action": "event_normalised",
      "actor": "system",
      "timestamp": "2026-11-03T09:00:01Z",
      "details": {}
    },
    {
      "audit_id": "aud-003",
      "action": "assessment_started",
      "actor": "system",
      "timestamp": "2026-11-03T09:00:01Z",
      "details": { "agent_run_id": "run-xyz-789" }
    },
    {
      "audit_id": "aud-004",
      "action": "triage_completed",
      "actor": "triage_agent",
      "timestamp": "2026-11-03T09:00:03Z",
      "details": { "category": "after_hours_presence", "urgency_signals": ["after_hours", "restricted_zone"] }
    },
    {
      "audit_id": "aud-005",
      "action": "evidence_retrieved",
      "actor": "context_agent",
      "timestamp": "2026-11-03T09:00:08Z",
      "details": { "sources_queried": 4, "sources_available": 4, "evidence_ids": ["ACCESS-Q-221", "POL-203", "SCH-Q-882"] }
    },
    {
      "audit_id": "aud-006",
      "action": "risk_assessed",
      "actor": "risk_engine",
      "timestamp": "2026-11-03T09:00:09Z",
      "details": { "risk_score": 78, "risk_level": "critical", "policy_version": "1.0" }
    },
    {
      "audit_id": "aud-007",
      "action": "explanation_generated",
      "actor": "explanation_agent",
      "timestamp": "2026-11-03T09:00:12Z",
      "details": { "agent_run_id": "run-xyz-789" }
    },
    {
      "audit_id": "aud-008",
      "action": "awaiting_human_review",
      "actor": "system",
      "timestamp": "2026-11-03T09:00:12Z",
      "details": {}
    },
    {
      "audit_id": "aud-009",
      "action": "human_decision",
      "actor": "user-001",
      "actor_role": "officer",
      "timestamp": "2026-11-03T09:01:00Z",
      "details": {
        "decision": "escalate",
        "rationale": "No badge found, after-hours, restricted area.",
        "recommendation_id": "rec-abc-001"
      }
    },
    {
      "audit_id": "aud-010",
      "action": "escalated",
      "actor": "user-001",
      "timestamp": "2026-11-03T09:01:05Z",
      "details": { "destination": "shift_supervisor", "escalation_id": "esc-abc-001" }
    }
  ]
}
```

---

## 5. Integration Health API

### GET /api/v1/integrations/health

Get health status of all evidence sources.

**Required role:** `officer`, `supervisor`, `platform_admin`

**Response 200:**
```json
{
  "overall_status": "degraded",
  "checked_at": "2026-11-03T09:00:00Z",
  "sources": [
    {
      "source_id": "access_control",
      "name": "Access Control System",
      "status": "healthy",
      "last_successful_call": "2026-11-03T08:59:55Z",
      "latency_ms": 45,
      "error": null
    },
    {
      "source_id": "schedule",
      "name": "Schedule Service",
      "status": "degraded",
      "last_successful_call": "2026-11-03T08:45:00Z",
      "latency_ms": null,
      "error": "Connection timeout after 5000ms"
    }
  ]
}
```

---

## 6. Risk Policy API

### GET /api/v1/risk-policies

List all risk policy versions.

**Required role:** `security_admin`, `agent_admin`

**Response 200:**
```json
{
  "policies": [
    {
      "policy_id": "pol-001",
      "version": "1.0",
      "name": "Default MVP Policy",
      "is_active": true,
      "effective_from": "2026-11-03",
      "created_at": "2026-11-03T09:00:00Z"
    }
  ]
}
```

### GET /api/v1/risk-policies/{policy_id}

Get a specific risk policy with all factors.

**Response 200:**
```json
{
  "policy_id": "pol-001",
  "version": "1.0",
  "name": "Default MVP Policy",
  "is_active": true,
  "thresholds": {
    "low": { "min": 0, "max": 24 },
    "medium": { "min": 25, "max": 49 },
    "high": { "min": 50, "max": 74 },
    "critical": { "min": 75, "max": null }
  },
  "factors": [
    {
      "factor_id": "no_matching_badge",
      "label": "No matching authorised badge",
      "weight": 25,
      "direction": "increases_risk"
    }
  ]
}
```

---

## 7. Locations and Cameras API

### GET /api/v1/locations

**Required role:** Any authenticated

**Response 200:**
```json
{
  "locations": [
    {
      "location_id": "LOADING_DOCK_3",
      "name": "Loading Dock 3",
      "facility_id": "FACILITY-001",
      "zone_type": "restricted",
      "cameras": ["CAM-DOCK-03"]
    }
  ]
}
```

### GET /api/v1/cameras

**Required role:** Any authenticated

**Response 200:**
```json
{
  "cameras": [
    {
      "camera_id": "CAM-DOCK-03",
      "name": "Dock 3 Camera",
      "location_id": "LOADING_DOCK_3",
      "status": "active"
    }
  ]
}
```

---

## 8. Document History

| Version | Date | Author | Change |
|---------|------|--------|--------|
| 1.0 | 2026-11-03 | IBM Bob | Initial API contracts — Gate 1 |
