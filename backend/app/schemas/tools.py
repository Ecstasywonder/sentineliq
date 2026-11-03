"""
Pydantic response schemas for Gate 7 context-tool endpoints.

Each schema mirrors the corresponding ORM model but is read-only
and safe to serialise directly in API responses.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------


class ToolMeta(BaseModel):
    """Metadata appended to every tool response."""

    source: str = Field(..., description="Adapter / integration source identifier")
    record_count: int = Field(..., ge=0)
    truncated: bool = False


# ---------------------------------------------------------------------------
# Access Events tool
# ---------------------------------------------------------------------------


class AccessEventRecord(BaseModel):
    id: str
    location_id: str
    facility_id: str | None = None
    badge_id: str | None = None
    person_ref: str | None = None
    access_type: str  # entry / exit / denied
    access_granted: bool
    occurred_at: str
    source_system: str


class AccessEventsResponse(BaseModel):
    meta: ToolMeta
    records: list[AccessEventRecord]


# ---------------------------------------------------------------------------
# Schedule tool
# ---------------------------------------------------------------------------


class ScheduleRecord(BaseModel):
    id: str
    facility_id: str | None = None
    location_id: str | None = None
    schedule_type: str
    person_ref: str | None = None
    description: str | None = None
    start_time: str
    end_time: str
    is_active: bool
    source_system: str


class ScheduleResponse(BaseModel):
    meta: ToolMeta
    records: list[ScheduleRecord]


# ---------------------------------------------------------------------------
# Work Orders tool
# ---------------------------------------------------------------------------


class WorkOrderRecord(BaseModel):
    id: str
    facility_id: str | None = None
    location_id: str
    work_order_number: str
    description: str | None = None
    assigned_to: str | None = None
    scheduled_start: str
    scheduled_end: str
    status: str
    requires_after_hours: bool
    approved_by: str | None = None
    source_system: str


class WorkOrdersResponse(BaseModel):
    meta: ToolMeta
    records: list[WorkOrderRecord]


# ---------------------------------------------------------------------------
# Delivery tool
# ---------------------------------------------------------------------------


class DeliveryRecord(BaseModel):
    id: str
    facility_id: str | None = None
    location_id: str
    supplier_name: str | None = None
    delivery_reference: str | None = None
    scheduled_start: str
    scheduled_end: str
    is_scheduled: bool
    notes: str | None = None
    source_system: str


class DeliveryResponse(BaseModel):
    meta: ToolMeta
    records: list[DeliveryRecord]


# ---------------------------------------------------------------------------
# Location Policy tool
# ---------------------------------------------------------------------------


class SecurityRuleRecord(BaseModel):
    id: str
    facility_id: str | None = None
    location_id: str | None = None
    rule_code: str
    rule_type: str
    description: str
    restricted_after: str | None = None
    restricted_before: str | None = None
    applies_to_zones: str | None = None
    is_active: bool
    policy_reference: str | None = None


class LocationPolicyResponse(BaseModel):
    meta: ToolMeta
    records: list[SecurityRuleRecord]


# ---------------------------------------------------------------------------
# Incident History tool
# ---------------------------------------------------------------------------


class IncidentRecord(BaseModel):
    id: str
    facility_id: str | None = None
    location_id: str
    incident_code: str
    incident_type: str
    severity: str
    occurred_at: str
    description: str
    outcome: str | None = None
    resolved: bool
    resolution_notes: str | None = None


class IncidentHistoryResponse(BaseModel):
    meta: ToolMeta
    records: list[IncidentRecord]


# ---------------------------------------------------------------------------
# Integration Health tool
# ---------------------------------------------------------------------------


class IntegrationHealthRecord(BaseModel):
    source_id: str
    name: str
    status: str
    last_checked_at: str | None = None
    last_successful_at: str | None = None
    latency_ms: float | None = None
    consecutive_failures: int
    error_message: str | None = None
    adapter_class: str | None = None


class IntegrationHealthResponse(BaseModel):
    meta: ToolMeta
    records: list[IntegrationHealthRecord]


# ---------------------------------------------------------------------------
# Aggregated Evidence (Gate 8 preview shape)
# ---------------------------------------------------------------------------


class AggregatedEvidence(BaseModel):
    """
    Full evidence bundle for a single event — produced by EvidenceAggregator.
    All fields are optional; missing data causes confidence reduction (ADR-004).
    """

    event_id: str
    access_events: AccessEventsResponse | None = None
    schedule: ScheduleResponse | None = None
    work_orders: WorkOrdersResponse | None = None
    delivery: DeliveryResponse | None = None
    location_policy: LocationPolicyResponse | None = None
    incident_history: IncidentHistoryResponse | None = None
    integration_health: IntegrationHealthResponse | None = None
    errors: dict[str, Any] = Field(default_factory=dict)
