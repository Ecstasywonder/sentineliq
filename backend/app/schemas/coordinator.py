"""
Coordinator schemas — Gate 17.

CoordinatorReview is the typed output of CoordinatorService.run().
The Coordinator is a read-only agent: it never scores risk, changes event
state, or makes an operational decision. It delegates to specialist agents
and returns a structured review for the operator dashboard.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CoordinatorAgentOutput(BaseModel):
    """Strict contract accepted from the untrusted Coordinator agent response."""

    model_config = ConfigDict(extra="forbid", strict=True)

    event_id: str = Field(min_length=1, max_length=128)
    assessment_ready: bool
    # No max_length here — the service truncates to 1024 after sanitisation
    summary: str = Field(min_length=1, max_length=8192)
    missing_evidence: list[str] = Field(max_length=64)
    human_review_required: bool


class CoordinatorReview(BaseModel):
    """
    Output of the Coordinator Agent (or deterministic fallback).

    ``source`` values:
      - ``"orchestrate"``            — Path B (Orchestrate SaaS)
      - ``"deterministic_fallback"`` — Path 0 (rule-based, Orchestrate unavailable)
    """

    event_id: str
    assessment_ready: bool = False
    summary: str = Field(default="", max_length=1024)
    missing_evidence: list[str] = Field(default_factory=list)
    human_review_required: bool = True
    source: str = "deterministic_fallback"
    agent_run_id: str | None = None


class CoordinatorReviewResponse(BaseModel):
    """API response for GET /events/{id}/review."""

    event_id: str
    assessment_ready: bool
    summary: str
    missing_evidence: list[str]
    human_review_required: bool
    source: str
    agent_run_id: str | None
