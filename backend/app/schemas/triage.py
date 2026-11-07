"""
Triage schemas — Gate 14.

TriageResult is the typed output of TriageService.  It is used by
AssessmentService and exposed in AssessmentResponse so operators can
see the triage classification.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TriageAgentOutput(BaseModel):
    """Strict contract accepted from an untrusted triage agent."""

    model_config = ConfigDict(extra="forbid", strict=True)

    event_id: str = Field(min_length=1, max_length=128)
    category: Literal[
        "after_hours_presence",
        "restricted_area_access",
        "delivery_event",
        "authorized_access",
        "alarm_event",
        "vehicle_event",
        "unclassified",
    ]
    urgency_signals: list[
        Literal[
            "after_hours",
            "restricted_zone",
            "forced_entry",
            "no_camera_coverage",
            "repeated_event",
            "low_detector_confidence",
            "missing_event_metadata",
        ]
    ]
    required_context: list[
        Literal[
            "access_control",
            "schedule",
            "location_policy",
            "incident_history",
            "work_orders",
            "delivery_context",
            "visitor_context",
            "integration_health",
        ]
    ]
    triage_rationale: str = Field(min_length=1, max_length=512)


class TriageResult(BaseModel):
    """
    Output of the Triage Agent (or deterministic fallback).

    ``source`` distinguishes a live Orchestrate result from a fallback:
      - "orchestrate"            — validated agent response
      - "deterministic_fallback" — Orchestrate unavailable or returned invalid output
      - "skipped"                — Orchestrate not configured (no credentials)
    """

    event_id: str
    category: str
    urgency_signals: list[str] = Field(default_factory=list)
    required_context: list[str] = Field(default_factory=list)
    triage_rationale: str = Field(default="", max_length=512)
    agent_run_id: str | None = Field(default=None)
    source: str = Field(default="orchestrate")


class TriageResultDetail(BaseModel):
    """
    TriageResult serialised for inclusion in AssessmentResponse.
    Exposed to API consumers.
    """

    category: str
    urgency_signals: list[str]
    required_context: list[str]
    triage_rationale: str
    source: str
    agent_run_id: str | None
