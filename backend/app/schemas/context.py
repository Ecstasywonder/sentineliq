"""
Context schemas — Gate 15.

ContextResult is the typed output of ContextService. It is used by
AssessmentService and exposed in AssessmentResponse so operators can
see what each evidence source found.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ContextSourceName = Literal[
    "access_control",
    "schedule",
    "location_policy",
    "incident_history",
    "work_orders",
    "delivery_context",
    "visitor_context",
    "integration_health",
]


class SourceStatusRecord(BaseModel):
    """Status and summary of a single evidence source."""

    status: str  # verified_present | verified_absent | unavailable | not_requested
    record_count: int | None = None
    summary: str | None = None


class EvidenceConflict(BaseModel):
    """A detected conflict between two evidence sources."""

    source_a: str
    source_b: str
    description: str


class ContextAgentSourceStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    status: Literal[
        "verified_present",
        "verified_absent",
        "unavailable",
        "not_requested",
    ]
    record_count: int | None = Field(default=None, ge=0)
    summary: str | None = Field(default=None, max_length=256)


class ContextAgentConflict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    source_a: str = Field(min_length=1, max_length=64)
    source_b: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=512)


class ContextAgentOutput(BaseModel):
    """Strict contract accepted from an untrusted context agent."""

    model_config = ConfigDict(extra="forbid", strict=True)

    event_id: str = Field(min_length=1, max_length=128)
    source_statuses: dict[ContextSourceName, ContextAgentSourceStatus] = Field(max_length=8)
    conflicts: list[ContextAgentConflict] = Field(max_length=20)
    missing_sources: list[ContextSourceName] = Field(max_length=8)
    context_summary: str = Field(max_length=1024)
    has_conflicts: bool
    has_missing_sources: bool


class ContextResult(BaseModel):
    """
    Output of the Context Agent (or deterministic fallback).

    ``source`` values:
      - "orchestrate"            — Path B (Orchestrate SaaS)
      - "watsonx_ai"             — Path A (watsonx.ai Chat API, verified)
      - "deterministic_fallback" — Path 0 (rule-based, no LLM)
    """

    event_id: str
    source_statuses: dict[str, SourceStatusRecord] = Field(default_factory=dict)
    conflicts: list[EvidenceConflict] = Field(default_factory=list)
    missing_sources: list[str] = Field(default_factory=list)
    context_summary: str = Field(default="", max_length=1024)
    has_conflicts: bool = False
    has_missing_sources: bool = False
    agent_run_id: str | None = None
    source: str = "orchestrate"


class ContextResultDetail(BaseModel):
    """ContextResult serialised for inclusion in AssessmentResponse."""

    source_statuses: dict[str, SourceStatusRecord]
    conflicts: list[EvidenceConflict]
    missing_sources: list[str]
    context_summary: str
    has_conflicts: bool
    has_missing_sources: bool
    source: str
    agent_run_id: str | None
