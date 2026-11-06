"""
Pydantic schemas for the Risk Assessment API — Gate 8 / Triage Gate 14.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.context import ContextResultDetail
from app.schemas.triage import TriageResultDetail

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

    # Triage (agent classification — Gate 14)
    triage: TriageResultDetail | None = None

    # Context (agent evidence interpretation — Gate 15)
    context: ContextResultDetail | None = None

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


# ---------------------------------------------------------------------------
# GET /events/{id}/assessment — persisted assessment retrieval (Gate 9)
# ---------------------------------------------------------------------------


class AssessmentFactorsResponse(BaseModel):
    """
    Per-factor breakdown for a persisted assessment.

    Returned by GET /api/v1/events/{id}/assessment/factors.
    Each item carries the same fields as RiskFactorDetail plus a human-readable
    description sourced from the RiskPolicyFactor definition row.
    """

    assessment_id: str
    event_id: str
    risk_policy_version: str
    risk_score: float
    risk_level: str
    factors: list[RiskFactorDetail]
    assessed_at: str


class AssessmentRetrievalResponse(BaseModel):
    """
    Assessment bundle read from persisted DB rows.

    Returned by GET /api/v1/events/{id}/assessment.
    Does not include live evidence errors (those are stored separately);
    returns the stored factor breakdown and confidence reductions from JSON.
    """

    assessment_id: str
    event_id: str
    risk_policy_version: str
    risk_score: float
    risk_level: str
    risk_factors: list[RiskFactorDetail]

    confidence_score: float
    confidence_level: str
    confidence_reductions: list[ConfidenceReductionDetail]
    sources_available: int
    sources_required: int

    assessed_at: str
    agent_run_id: str | None = None


# ---------------------------------------------------------------------------
# GET /risk-policies — Risk Policy API (Gate 9)
# ---------------------------------------------------------------------------


class RiskPolicyFactorResponse(BaseModel):
    """Single factor within a risk policy."""

    factor_id: str
    label: str
    weight: float
    direction: str
    is_active: bool
    description: str | None = None


class RiskPolicyResponse(BaseModel):
    """Single risk policy with its factors."""

    id: str
    version: str
    name: str
    description: str | None = None
    is_active: bool
    effective_from: str | None = None
    factors: list[RiskPolicyFactorResponse]


class RiskPolicyListResponse(BaseModel):
    """Paginated list of risk policies."""

    items: list[RiskPolicyResponse]
    total: int
