"""
Explanation schemas — Master Build Prompt Gate 13.

ExplanationResult is the typed output of ExplanationService. It is used by
AssessmentService and exposed in AssessmentResponse so operators can read
a grounded, evidence-cited narrative for every assessed event.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class WhyReason(BaseModel):
    """A single grounded reason within the explanation."""

    text: str
    evidence_ids: list[str] = Field(min_length=1)


class ExplanationResult(BaseModel):
    """
    Output of the Explanation Agent (or deterministic fallback).

    ``source`` values:
      - "orchestrate"            — Path B (Orchestrate SaaS)
      - "watsonx_ai"             — Path A (watsonx.ai Chat API, verified)
      - "deterministic_fallback" — Path 0 (rule-based, no LLM)
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
    agent_run_id: str | None = None
    source: str = "orchestrate"


class ExplanationResultDetail(BaseModel):
    """ExplanationResult serialised for inclusion in AssessmentResponse."""

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
