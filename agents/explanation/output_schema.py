"""
Explanation Agent output schema — Master Build Prompt Gate 13.

Mirrors the output_schema in agents/explanation/agent.yaml.
Used by ExplanationService to validate LLM output and as the typed
result used downstream by AssessmentService and the API.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class WhyReason(BaseModel):
    """A single grounded reason explaining the assessment."""

    text: str
    evidence_ids: list[str] = Field(min_length=1)


class ExplanationResult(BaseModel):
    """
    Output of the Explanation Agent (or deterministic fallback).

    ``source`` distinguishes which path produced the result:
      - "orchestrate"            — Path B validated agent response
      - "watsonx_ai"             — Path A validated agent response
      - "deterministic_fallback" — all LLM paths unavailable or failed
    """

    event_id: str
    summary: str = Field(default="", max_length=512)
    risk_level: str = "medium"
    risk_score: float = 0.0
    confidence_score: float = 0.0
    why: list[WhyReason] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    recommended_action: str = Field(default="", max_length=512)
    has_missing_evidence: bool = False
    has_limitations: bool = False
    # Metadata added by ExplanationService
    agent_run_id: str | None = None
    source: str = "orchestrate"


class ExplanationResultDetail(BaseModel):
    """
    ExplanationResult serialised for inclusion in AssessmentResponse.
    Exposed to API consumers.
    """

    summary: str
    risk_level: str
    risk_score: float
    confidence_score: float
    why: list[WhyReason]
    missing_evidence: list[str]
    limitations: list[str]
    recommended_action: str
    has_missing_evidence: bool
    has_limitations: bool
    source: str
    agent_run_id: str | None
