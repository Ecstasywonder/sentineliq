"""
Pydantic schemas for the Feedback API — Gate 13.

Feedback captures operator/reviewer quality assessments after a decision is
made.  It is the primary training signal for continuous improvement of the
risk engine and agent recommendations.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

VALID_OUTCOMES = frozenset(
    {
        "confirmed_incident",
        "false_positive",
        "authorized_activity",
        "insufficient_information",
        "other",
    }
)


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


class FeedbackRequest(BaseModel):
    """
    Payload for POST /api/v1/events/{id}/feedback.

    All fields are optional except the schema itself — callers may submit
    partial feedback (e.g. just an outcome, or just a usefulness rating).
    """

    recommendation_useful: bool | None = Field(
        None,
        description="Was the agent recommendation useful to the operator?",
    )
    recommendation_accurate: bool | None = Field(
        None,
        description="Was the risk assessment accurate in hindsight?",
    )
    outcome: str | None = Field(
        None,
        description=f"Actual outcome of the event. Valid: {sorted(VALID_OUTCOMES)}",
    )
    missing_context: str | None = Field(
        None,
        max_length=1000,
        description="Description of any context the system lacked.",
    )
    notes: str | None = Field(
        None,
        max_length=2000,
        description="Free-text notes for the quality review team.",
    )


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------


class FeedbackResponse(BaseModel):
    """Single feedback submission."""

    feedback_id: str
    event_id: str
    submitted_by: str
    recommendation_useful: bool | None
    recommendation_accurate: bool | None
    outcome: str | None
    missing_context: str | None
    notes: str | None
    submitted_at: str


class FeedbackListResponse(BaseModel):
    """All feedback records for a single event."""

    event_id: str
    items: list[FeedbackResponse]
    total: int
