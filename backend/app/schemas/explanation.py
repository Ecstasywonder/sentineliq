"""
Explanation schemas — Master Build Prompt Gate 13.

ExplanationResult is the typed output of ExplanationService. It is used by
AssessmentService and exposed in AssessmentResponse so operators can read
a grounded, evidence-cited narrative for every assessed event.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


EvidenceId = Annotated[str, Field(min_length=1, max_length=128)]
MissingEvidenceLine = Annotated[str, Field(min_length=1, max_length=256)]
LimitationLine = Annotated[str, Field(min_length=1, max_length=512)]


class WhyReason(BaseModel):
    """A single grounded reason within the explanation."""

    model_config = ConfigDict(extra="forbid", strict=True)

    text: str = Field(min_length=1, max_length=512)
    evidence_ids: list[EvidenceId] = Field(min_length=1, max_length=20)


class ExplanationAgentOutput(BaseModel):
    """Strict, complete contract accepted from an untrusted agent response."""

    model_config = ConfigDict(extra="forbid", strict=True)

    event_id: str = Field(min_length=1, max_length=128)
    summary: str = Field(min_length=1, max_length=512)
    risk_level: Literal["low", "medium", "high", "critical"]
    risk_score: float = Field(ge=0.0, le=200.0)
    confidence_score: float = Field(ge=0.0, le=1.0)
    why: list[WhyReason] = Field(max_length=20)
    missing_evidence: list[MissingEvidenceLine] = Field(max_length=32)
    limitations: list[LimitationLine] = Field(max_length=32)
    recommended_action: str = Field(min_length=1, max_length=512)
    has_missing_evidence: bool
    has_limitations: bool


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


class AssessmentBundleResponse(BaseModel):
    """Persisted reconstruction bundle exposed to the read-only agent tool."""

    event_id: str
    event_status: str
    risk_score: float
    risk_level: str
    risk_policy_version: str
    risk_factors: list[dict[str, Any]] = Field(default_factory=list)
    confidence_score: float | None = None
    confidence_level: str | None = None
    triage: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    explanation: dict[str, Any] = Field(default_factory=dict)
    evidence_errors: dict[str, str] = Field(default_factory=dict)
    workflow_state: dict[str, Any] = Field(default_factory=dict)
    assessed_at: str
