"""
Pydantic schemas for the Risk Assessment API — Gate 8.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


class AssessEventRequest(BaseModel):
    """
    Optional caller-supplied overrides for the assessment run.

    All fields are optional — the assessment service can run with zero input
    because it derives all signals from the evidence it retrieves itself.
    """

    # Caller may hint that specific sources are unavailable (e.g. during
    # a known integration outage).  These supplement what the aggregator
    # discovers automatically.
    unavailable_source_ids: list[str] = Field(
        default_factory=list,
        description="Source IDs the caller knows are unavailable.",
    )

    # Force a specific policy version (defaults to Settings.active_risk_policy_version)
    policy_version: str | None = Field(
        None,
        description="Override the active risk policy version.",
    )


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------


class RiskFactorDetail(BaseModel):
    factor_id: str
    label: str
    weight: float
    direction: str
    triggered: bool
    contribution: float


class ConfidenceReductionDetail(BaseModel):
    reason: str
    amount: float
    source_id: str = ""
    detail: str = ""


class AssessmentResponse(BaseModel):
    """Full assessment bundle returned by POST /events/{id}/assess."""

    event_id: str
    event_status: str

    # Risk (deterministic, ADR-003)
    risk_score: float
    risk_level: str
    risk_policy_version: str
    risk_factors: list[RiskFactorDetail]

    # Confidence (independent, ADR-004)
    confidence_score: float
    confidence_level: str
    confidence_reductions: list[ConfidenceReductionDetail]
    sources_available: int
    sources_required: int

    # Evidence errors (sources that failed to respond)
    evidence_errors: dict[str, str]

    assessed_at: str
