"""
Pydantic schemas for the Escalation API — Gate 11.

Escalations are created automatically when an operator records a decision
of type 'escalate'.  They can also be created directly via POST.
The escalation lifecycle is: pending_acknowledgement → acknowledged → resolved | cancelled.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

VALID_ESCALATION_STATUSES = frozenset(
    {"pending_acknowledgement", "acknowledged", "resolved", "cancelled"}
)

VALID_DESTINATIONS = frozenset(
    {"shift_supervisor", "response_team", "security_admin", "external"}
)

VALID_PRIORITIES = frozenset({"low", "medium", "high", "critical"})

# Valid status transitions for an Escalation record
ESCALATION_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending_acknowledgement": frozenset({"acknowledged", "cancelled"}),
    "acknowledged": frozenset({"resolved", "cancelled"}),
    "resolved": frozenset(),
    "cancelled": frozenset(),
}


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class EscalationCreateRequest(BaseModel):
    """
    Payload for POST /api/v1/events/{id}/escalation.

    Destination and priority are required.  Note is strongly recommended.
    When called automatically from a 'escalate' decision, the decision
    service passes these through.
    """

    destination: str = Field(
        ...,
        description=f"Escalation target. Valid: {sorted(VALID_DESTINATIONS)}",
    )
    priority: str = Field(
        "high",
        description=f"Escalation priority. Valid: {sorted(VALID_PRIORITIES)}",
    )
    note: str | None = Field(
        None,
        max_length=2000,
        description="Free-text note for the receiving party.",
    )


class EscalationUpdateRequest(BaseModel):
    """
    Payload for PATCH /api/v1/events/{id}/escalation.

    Used to acknowledge or resolve/cancel an escalation.
    """

    status: str = Field(
        ...,
        description=f"New escalation status. Valid: {sorted(VALID_ESCALATION_STATUSES)}",
    )
    note: str | None = Field(
        None,
        max_length=2000,
        description="Optional note to append when updating status.",
    )


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class EscalationResponse(BaseModel):
    """Single escalation record."""

    escalation_id: str
    event_id: str
    destination: str
    priority: str
    status: str
    note: str | None
    escalated_by: str
    escalated_by_role: str
    escalated_at: str
    acknowledged_by: str | None
    acknowledged_at: str | None
    # Current event status (denormalised for UI convenience)
    event_status: str
