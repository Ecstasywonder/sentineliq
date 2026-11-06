"""
Context Agent output schema — Gate 15.

Mirrors the output_schema in agents/context/agent.yaml.
Used by ContextService to validate LLM output and as the typed
result used downstream by AssessmentService.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SourceStatusRecord(BaseModel):
    """Status of a single evidence source."""

    status: str  # verified_present | verified_absent | unavailable | not_requested
    record_count: int | None = None
    summary: str | None = None


class EvidenceConflict(BaseModel):
    """A detected conflict between two evidence sources."""

    source_a: str
    source_b: str
    description: str


class ContextResult(BaseModel):
    """
    Output of the Context Agent (or deterministic fallback).

    ``source`` distinguishes which path produced the result:
      - "orchestrate"            — Path B validated agent response
      - "watsonx_ai"             — Path A validated agent response
      - "deterministic_fallback" — all LLM paths unavailable or failed
    """

    event_id: str
    source_statuses: dict[str, SourceStatusRecord] = Field(default_factory=dict)
    conflicts: list[EvidenceConflict] = Field(default_factory=list)
    missing_sources: list[str] = Field(default_factory=list)
    context_summary: str = Field(default="", max_length=1024)
    has_conflicts: bool = False
    has_missing_sources: bool = False
    # Metadata added by ContextService
    agent_run_id: str | None = None
    source: str = "orchestrate"


class ContextResultDetail(BaseModel):
    """
    ContextResult serialised for inclusion in AssessmentResponse.
    Exposed to API consumers.
    """

    source_statuses: dict[str, SourceStatusRecord]
    conflicts: list[EvidenceConflict]
    missing_sources: list[str]
    context_summary: str
    has_conflicts: bool
    has_missing_sources: bool
    source: str
    agent_run_id: str | None
