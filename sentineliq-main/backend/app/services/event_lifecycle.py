"""
Event lifecycle state machine — Gate 5.

Enforces valid status transitions for SecurityEvent (ADR-006 / architecture §8).
Invalid transitions raise a structured ValueError — callers convert to HTTP 409.

Valid lifecycle:

    RECEIVED
        └─► NORMALISED
                └─► ASSESSING ──────────────────────────► CONTEXT_INCOMPLETE
                        └─► AWAITING_REVIEW               └─► FAILED
                                ├─► DISMISSED
                                ├─► CLOSED
                                └─► ESCALATED ──────────► CLOSED
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Transition map
# ---------------------------------------------------------------------------

# Maps current status → set of allowed next statuses
_TRANSITIONS: dict[str, frozenset[str]] = {
    "received": frozenset({"normalised", "failed"}),
    "normalised": frozenset({"assessing", "failed"}),
    "assessing": frozenset({"awaiting_review", "context_incomplete", "failed"}),
    "awaiting_review": frozenset({"dismissed", "closed", "escalated", "assessing", "context_incomplete"}),
    "context_incomplete": frozenset({"awaiting_review", "failed", "assessing"}),
    "escalated": frozenset({"closed", "awaiting_review"}),
    # Terminal states — no further transitions
    "dismissed": frozenset(),
    "closed": frozenset(),
    "failed": frozenset(),
}

# Statuses from which a human decision is required (human review non-bypassable)
HUMAN_REVIEW_STATUSES: frozenset[str] = frozenset(
    {"dismissed", "closed", "escalated"}
)

# Statuses considered terminal (no further state changes permitted)
TERMINAL_STATUSES: frozenset[str] = frozenset({"dismissed", "closed", "failed"})


# ---------------------------------------------------------------------------
# Transition enforcement
# ---------------------------------------------------------------------------


class InvalidTransitionError(ValueError):
    """Raised when an attempted status transition is not permitted."""

    def __init__(self, current: str, requested: str) -> None:
        self.current = current
        self.requested = requested
        super().__init__(
            f"Transition '{current}' -> '{requested}' is not permitted. "
            f"Allowed from '{current}': {sorted(_TRANSITIONS.get(current, set()))}"
        )


def validate_transition(current_status: str, new_status: str) -> None:
    """
    Assert that transitioning from *current_status* to *new_status* is valid.

    Raises:
        InvalidTransitionError: if the transition is not in the allowed set.
    """
    allowed = _TRANSITIONS.get(current_status, frozenset())
    if new_status not in allowed:
        raise InvalidTransitionError(current_status, new_status)


def allowed_transitions(current_status: str) -> list[str]:
    """Return the list of valid next statuses from *current_status*."""
    return sorted(_TRANSITIONS.get(current_status, frozenset()))


def is_terminal(status: str) -> bool:
    """Return True if *status* is a terminal state."""
    return status in TERMINAL_STATUSES
