"""
Context schemas — Gate 15.

ContextResult is the typed output of ContextService. It is used by
AssessmentService and exposed in AssessmentResponse so operators can
see what each evidence source found.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


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


class ContextAgentOutput(BaseModel):
    """Narrow contract accepted from an untrusted context agent.

    The LLM is trusted only for ``context_summary`` — a two-sentence
    operator-readable narrative.  All structural fields (source_statuses,
    conflicts, missing_sources, flags) are derived from raw evidence by the
    deterministic engine and cannot be overridden by the agent.
    """

    model_config = ConfigDict(extra="ignore", strict=False)

    event_id: str = Field(min_length=1, max_length=128)
    context_summary: str = Field(max_length=1024)


class ContextResult(BaseModel):
    """
    Output of the Context Agent (or deterministic fallback).

    ``source`` values:
      - "orchestrate"            — Path B (Orchestrate SaaS)
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
