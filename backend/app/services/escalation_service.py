"""
EscalationService — Gate 11.

Orchestrates the escalation lifecycle:
  CREATE:
    1. Validate event is in 'escalated' status
    2. Validate destination + priority
    3. Persist Escalation row (status=pending_acknowledgement)
    4. Write immutable AuditEvent row (action='escalated')

  UPDATE:
    1. Load existing Escalation row (404 if absent)
    2. Validate status transition (ESCALATION_TRANSITIONS)
    3. If acknowledging: stamp acknowledged_by + acknowledged_at
    4. Persist updated row
    5. Write immutable AuditEvent row (action='status_changed')
    6. If resolving/cancelling: transition event → closed/awaiting_review

Design constraints:
  - AuditEvent rows are INSERT-only — never modified after creation.
  - Escalation rows are the source of truth; SecurityEvent.status is
    kept in sync but is derived state.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditEvent
from app.models.escalation import Escalation
from app.models.event import SecurityEvent
from app.schemas.escalation import (
    ESCALATION_TRANSITIONS,
    VALID_DESTINATIONS,
    VALID_PRIORITIES,
    EscalationResponse,
)
from app.security.dependencies import AuthenticatedUser
from app.services.event_lifecycle import validate_transition

logger = structlog.get_logger(__name__)


def _now() -> str:
    return datetime.now(UTC).isoformat()


class InvalidEscalationTransitionError(ValueError):
    """Raised when an escalation status transition is not permitted."""

    def __init__(self, current: str, requested: str) -> None:
        allowed = sorted(ESCALATION_TRANSITIONS.get(current, set()))
        super().__init__(
            f"Escalation transition '{current}' -> '{requested}' is not permitted. "
            f"Allowed from '{current}': {allowed}"
        )


class EscalationService:
    """
    Create and update Escalation records.

    Parameters
    ----------
    session:
        Active async DB session — caller owns commit/rollback.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create(
        self,
        event_id: str,
        destination: str,
        priority: str,
        note: str | None,
        actor: AuthenticatedUser,
    ) -> EscalationResponse:
        """
        Create an escalation for *event_id*.

        The event must already be in 'escalated' status (set by the
        decision service when the operator chose 'escalate').

        Raises:
            ValueError: Event not found, wrong status, or invalid params.
        """
        # ---- 1. Load event -----------------------------------------------
        event = await self._load_event(event_id)

        if event.status != "escalated":
            raise ValueError(
                f"Event '{event_id}' is in status '{event.status}'. "
                "Escalations can only be created for events in 'escalated' status."
            )

        # ---- 2. Validate params ------------------------------------------
        if destination not in VALID_DESTINATIONS:
            raise ValueError(
                f"Unknown destination '{destination}'. "
                f"Valid: {sorted(VALID_DESTINATIONS)}"
            )
        if priority not in VALID_PRIORITIES:
            raise ValueError(
                f"Unknown priority '{priority}'. "
                f"Valid: {sorted(VALID_PRIORITIES)}"
            )

        # ---- 3. Persist Escalation row -----------------------------------
        actor_role = actor.roles[0] if actor.roles else "unknown"
        escalated_at = _now()

        row = Escalation(
            id=str(uuid.uuid4()),
            event_id=event_id,
            escalated_by=actor.id,
            escalated_by_role=actor_role,
            destination=destination,
            priority=priority,
            note=note,
            status="pending_acknowledgement",
            escalated_at=escalated_at,
        )
        self._session.add(row)

        # ---- 4. Write immutable AuditEvent -------------------------------
        self._session.add(AuditEvent(
            id=str(uuid.uuid4()),
            event_id=event_id,
            action="escalated",
            actor=actor.email,
            actor_role=actor_role,
            occurred_at=escalated_at,
            details_json=json.dumps({
                "escalation_id": row.id,
                "destination": destination,
                "priority": priority,
                "note_provided": note is not None,
            }),
        ))

        await self._session.flush()

        logger.info(
            "escalation_service.created",
            event_id=event_id,
            escalation_id=row.id,
            destination=destination,
            priority=priority,
        )

        return self._to_response(row, event)

    # ------------------------------------------------------------------
    # Get latest
    # ------------------------------------------------------------------

    async def get_latest(self, event_id: str) -> Escalation | None:
        """Return the most recent Escalation for *event_id*, or None."""
        stmt = (
            select(Escalation)
            .where(Escalation.event_id == event_id)
            .order_by(Escalation.escalated_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Update status
    # ------------------------------------------------------------------

    async def update_status(
        self,
        event_id: str,
        new_status: str,
        note: str | None,
        actor: AuthenticatedUser,
    ) -> EscalationResponse:
        """
        Transition an escalation to *new_status*.

        - 'acknowledged': stamps acknowledged_by/at on the row
        - 'resolved': transitions event back to closed
        - 'cancelled': transitions event back to awaiting_review

        Raises:
            ValueError: Escalation not found, or invalid status.
            InvalidEscalationTransitionError: Transition not permitted.
        """
        # Load event + escalation
        event = await self._load_event(event_id)
        row = await self.get_latest(event_id)
        if row is None:
            raise ValueError(
                f"No escalation found for event '{event_id}'."
            )

        # Validate escalation status transition
        if new_status not in ESCALATION_TRANSITIONS.get(row.status, frozenset()):
            raise InvalidEscalationTransitionError(row.status, new_status)

        actor_role = actor.roles[0] if actor.roles else "unknown"
        occurred_at = _now()

        # Apply transition
        old_status = row.status
        row.status = new_status

        if new_status == "acknowledged":
            row.acknowledged_by = actor.id
            row.acknowledged_at = occurred_at

        if note:
            # Append to existing note
            row.note = f"{row.note}\n\n[{occurred_at}] {note}" if row.note else note

        self._session.add(row)

        # Sync event status
        if new_status == "resolved":
            validate_transition(event.status, "closed")
            event.status = "closed"
            self._session.add(event)
        elif new_status == "cancelled":
            validate_transition(event.status, "awaiting_review")
            event.status = "awaiting_review"
            self._session.add(event)

        # Immutable audit entry
        self._session.add(AuditEvent(
            id=str(uuid.uuid4()),
            event_id=event_id,
            action="status_changed",
            actor=actor.email,
            actor_role=actor_role,
            occurred_at=occurred_at,
            details_json=json.dumps({
                "entity": "escalation",
                "escalation_id": row.id,
                "old_status": old_status,
                "new_status": new_status,
                "note_provided": note is not None,
            }),
        ))

        await self._session.flush()

        logger.info(
            "escalation_service.updated",
            event_id=event_id,
            escalation_id=row.id,
            old_status=old_status,
            new_status=new_status,
        )

        return self._to_response(row, event)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _load_event(self, event_id: str) -> SecurityEvent:
        stmt = select(SecurityEvent).where(SecurityEvent.id == event_id)
        result = await self._session.execute(stmt)
        event: SecurityEvent | None = result.scalar_one_or_none()
        if event is None:
            raise ValueError(f"Event '{event_id}' not found.")
        return event

    @staticmethod
    def _to_response(row: Escalation, event: SecurityEvent) -> EscalationResponse:
        return EscalationResponse(
            escalation_id=row.id,
            event_id=row.event_id,
            destination=row.destination,
            priority=row.priority,
            status=row.status,
            note=row.note,
            escalated_by=row.escalated_by,
            escalated_by_role=row.escalated_by_role,
            escalated_at=row.escalated_at,
            acknowledged_by=row.acknowledged_by,
            acknowledged_at=row.acknowledged_at,
            event_status=event.status,
        )
