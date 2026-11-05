"""
Pydantic schemas for the Operator Decision API — Gate 10.

Decisions are the primary human-in-the-loop artefact in SentinelIQ.
Every decision advances the event lifecycle and creates an immutable
audit trail entry.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# Valid decision types (mirrors DECISION_TYPES in app/models/decision.py)
VALID_DECISIONS = frozenset(
    {"accept", "reject", "dismiss", "request_context", "escalate", "override"}
)

# Maps each decision type → required event status transition
DECISION_STATUS_MAP: dict[str, str] = {
    "accept": "closed",
    "reject": "dismissed",
    "dismiss": "dismissed",
    "escalate": "escalated",
    "override": "closed",
    "request_context": "context_incomplete",
}


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


class DecisionRequest(BaseModel):
    """
    Payload for POST /api/v1/events/{id}/decision.

    ``decision`` is required.  ``rationale`` is strongly recommended for
    audit trail quality but is technically optional to accommodate rapid
    triage workflows.
    """

    decision: str = Field(
        ...,
        description=(
            f"Operator decision type. Valid values: {sorted(VALID_DECISIONS)}"
        ),
    )
    rationale: str | None = Field(
        None,
        max_length=2000,
        description="Human-readable rationale for this decision (recommended).",
    )
    recommendation_id: str | None = Field(
        None,
        description="ID of the agent recommendation this decision responds to (optional).",
    )
    is_override: bool = Field(
        False,
        description="True if the operator is overriding an agent recommendation.",
    )


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------


class DecisionResponse(BaseModel):
    """
    Single operator decision returned by POST or GET
    /api/v1/events/{id}/decision.
    """

    decision_id: str
    event_id: str
    decision: str
    rationale: str | None
    recommendation_id: str | None
    is_override: bool
    decided_by: str
    decided_by_role: str
    prior_status: str | None
    risk_at_decision: str | None
    confidence_at_decision: float | None
    decided_at: str
    # Resulting event status after the decision was applied
    event_status: str


class DecisionListResponse(BaseModel):
    """All decisions recorded for a single event, newest first."""

    event_id: str
    items: list[DecisionResponse]
    total: int
