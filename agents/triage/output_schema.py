"""
Triage Agent output schema — Gate 14.

This Pydantic model mirrors the JSON output_schema defined in agent.yaml.
It is used to:
  1. Validate the structured JSON response received from Orchestrate.
  2. Provide the typed TriageResult used by TriageService callers.
  3. Serve as documentation of the agent contract.

Do NOT change field names or enum values without also updating agent.yaml
and the corresponding test fixtures.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class TriageCategory(StrEnum):
    """Allowed triage category values (must match agent.yaml enum)."""

    AFTER_HOURS_PRESENCE = "after_hours_presence"
    RESTRICTED_AREA_ACCESS = "restricted_area_access"
    DELIVERY_EVENT = "delivery_event"
    AUTHORIZED_ACCESS = "authorized_access"
    ALARM_EVENT = "alarm_event"
    VEHICLE_EVENT = "vehicle_event"
    UNCLASSIFIED = "unclassified"


class TriageUrgencySignal(StrEnum):
    """Allowed urgency signal values (must match agent.yaml)."""

    AFTER_HOURS = "after_hours"
    RESTRICTED_ZONE = "restricted_zone"
    FORCED_ENTRY = "forced_entry"
    NO_CAMERA_COVERAGE = "no_camera_coverage"
    REPEATED_EVENT = "repeated_event"
    LOW_DETECTOR_CONFIDENCE = "low_detector_confidence"
    MISSING_EVENT_METADATA = "missing_event_metadata"


class TriageRequiredContext(StrEnum):
    """Allowed required_context values (must match agent.yaml)."""

    ACCESS_CONTROL = "access_control"
    SCHEDULE = "schedule"
    LOCATION_POLICY = "location_policy"
    INCIDENT_HISTORY = "incident_history"
    WORK_ORDERS = "work_orders"
    DELIVERY_CONTEXT = "delivery_context"
    VISITOR_CONTEXT = "visitor_context"
    INTEGRATION_HEALTH = "integration_health"


class TriageResult(BaseModel):
    """
    Validated output from the Triage Agent.

    This is the canonical triage result type used throughout the backend.
    TriageService returns this on both successful Orchestrate calls and
    deterministic fallback.
    """

    event_id: str
    category: str  # TriageCategory value — kept as str for forward-compat
    urgency_signals: list[str] = Field(default_factory=list)
    required_context: list[str] = Field(default_factory=list)
    triage_rationale: str = Field(default="", max_length=512)
    # Metadata added by TriageService (not from agent output)
    agent_run_id: str | None = Field(default=None)
    source: str = Field(
        default="orchestrate",
        description="'orchestrate' | 'deterministic_fallback'",
    )
