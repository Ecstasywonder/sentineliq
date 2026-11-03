"""
DecisionService — Gate 10.

Orchestrates the operator decision pipeline:
  1. Load and validate the SecurityEvent (must be in awaiting_review or escalated)
  2. Validate the decision type
  3. Determine the target status (DECISION_STATUS_MAP)
  4. Validate the state machine transition
  5. Persist OperatorDecision row
  6. Write immutable AuditEvent row (action="human_decision")
  7. Advance event status

Design constraints:
  - Human decision is NON-BYPASSABLE (ADR-006): only events in
    awaiting_review or escalated may be decided.
  - Every decision creates an AuditEvent — no silent mutations.
  - The service never modifies AuditEvent rows after insertion.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditEvent
from app.models.decision import OperatorDecision
from app.models.escalation import Escalation
from app.models.event import SecurityEvent
from app.schemas.decision import (
    DECISION_STATUS_MAP,
    VALID_DECISIONS,
    DecisionResponse,
)
from app.security.dependencies import AuthenticatedUser
from app.services.event_lifecycle import validate_transition

logger = structlog.get_logger(__name__)

# Statuses from which an operator may make a decision (ADR-006)
_DECIDABLE_STATUSES: frozenset[str] = frozenset({"awaiting_review", "escalated"})


class DecisionService:
    """
    Persist an operator decision and advance the event lifecycle.

    Parameters
    ----------
    session:
        Active async DB session — the caller owns commit/rollback.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        event_id: str,
        decision_type: str,
        *,
        rationale: str | None,
        recommendation_id: str | None,
        is_override: bool,
        actor: AuthenticatedUser,
    ) -> DecisionResponse:
        """
        Record an operator decision on *event_id*.

        Args:
            event_id:          ID of the SecurityEvent.
            decision_type:     One of VALID_DECISIONS.
            rationale:         Free-text operator rationale.
            recommendation_id: Optional agent recommendation this responds to.
            is_override:       True when overriding an agent recommendation.
            actor:             Authenticated operator identity.

        Returns:
            DecisionResponse ready to serialise.

        Raises:
            ValueError:            Unknown event, invalid decision type, or
                                   event not in a decidable status.
            InvalidTransitionError: State machine rejects the transition.
        """
        # ---- 1. Load event -----------------------------------------------
        event = await self._load_event(event_id)

        # ---- 2. Validate decision type -----------------------------------
        if decision_type not in VALID_DECISIONS:
            raise ValueError(
                f"Unknown decision type '{decision_type}'. "
                f"Valid: {sorted(VALID_DECISIONS)}"
            )

        # ---- 3. Guard: event must be in a decidable status ---------------
        if event.status not in _DECIDABLE_STATUSES:
            raise ValueError(
                f"Event '{event_id}' is in status '{event.status}' and cannot "
                f"be decided. Events must be in {sorted(_DECIDABLE_STATUSES)} "
                "before an operator decision can be recorded."
            )

        # ---- 4. Determine target status and validate transition ----------
        target_status = DECISION_STATUS_MAP[decision_type]
        validate_transition(event.status, target_status)  # raises InvalidTransitionError

        prior_status = event.status
        decided_at = datetime.now(UTC).isoformat()
        actor_role = actor.roles[0] if actor.roles else "unknown"

        # ---- 5. Persist OperatorDecision row -----------------------------
        decision_row = OperatorDecision(
            id=str(uuid.uuid4()),
            event_id=event_id,
            recommendation_id=recommendation_id,
            decided_by=actor.id,
            decided_by_role=actor_role,
            decision=decision_type,
            rationale=rationale,
            is_override=is_override,
            prior_status=prior_status,
            risk_at_decision=event.risk_level,
            confidence_at_decision=event.confidence_score,
            decided_at=decided_at,
        )
        self._session.add(decision_row)

        # ---- 6. Write immutable AuditEvent row ---------------------------
        audit_row = AuditEvent(
            id=str(uuid.uuid4()),
            event_id=event_id,
            action="human_decision",
            actor=actor.email,
            actor_role=actor_role,
            occurred_at=decided_at,
            details_json=json.dumps({
                "decision": decision_type,
                "prior_status": prior_status,
                "target_status": target_status,
                "risk_at_decision": event.risk_level,
                "confidence_at_decision": event.confidence_score,
                "is_override": is_override,
                "recommendation_id": recommendation_id,
                "rationale_provided": rationale is not None,
            }),
        )
        self._session.add(audit_row)

        # ---- 7. Advance event status ------------------------------------
        event.status = target_status
        self._session.add(event)
        await self._session.flush()

        # ---- 8. Auto-create Escalation row when decision is 'escalate' --
        # The event is now in 'escalated' status; seed a default escalation
        # record so GET /escalation works immediately without an extra POST.
        if decision_type == "escalate":
            await self._auto_create_escalation(event_id, actor, actor_role, decided_at)

        await self._session.flush()

        logger.info(
            "decision_service.recorded",
            event_id=event_id,
            decision=decision_type,
            prior_status=prior_status,
            new_status=target_status,
            actor=actor.email,
        )

        return DecisionResponse(
            decision_id=decision_row.id,
            event_id=event_id,
            decision=decision_type,
            rationale=rationale,
            recommendation_id=recommendation_id,
            is_override=is_override,
            decided_by=actor.id,
            decided_by_role=actor_role,
            prior_status=prior_status,
            risk_at_decision=event.risk_level,
            confidence_at_decision=event.confidence_score,
            decided_at=decided_at,
            event_status=target_status,
        )

    async def get_latest(self, event_id: str) -> OperatorDecision | None:
        """
        Return the most recent OperatorDecision for *event_id*, or None.
        """
        from sqlalchemy import select

        stmt = (
            select(OperatorDecision)
            .where(OperatorDecision.event_id == event_id)
            .order_by(OperatorDecision.decided_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all(self, event_id: str) -> list[OperatorDecision]:
        """
        Return all OperatorDecision rows for *event_id*, newest first.
        """
        from sqlalchemy import select

        stmt = (
            select(OperatorDecision)
            .where(OperatorDecision.event_id == event_id)
            .order_by(OperatorDecision.decided_at.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _load_event(self, event_id: str) -> SecurityEvent:
        from sqlalchemy import select

        stmt = select(SecurityEvent).where(SecurityEvent.id == event_id)
        result = await self._session.execute(stmt)
        event: SecurityEvent | None = result.scalar_one_or_none()
        if event is None:
            raise ValueError(f"Event '{event_id}' not found.")
        return event

    async def _auto_create_escalation(
        self,
        event_id: str,
        actor: AuthenticatedUser,
        actor_role: str,
        escalated_at: str,
    ) -> None:
        """
        Seed a default Escalation row immediately after an 'escalate' decision.

        Uses 'shift_supervisor' as the default destination so the record is
        immediately queryable.  Operators can create a more specific escalation
        via POST /escalation if needed.
        """
        row = Escalation(
            id=str(uuid.uuid4()),
            event_id=event_id,
            escalated_by=actor.id,
            escalated_by_role=actor_role,
            destination="shift_supervisor",
            priority="high",
            note=None,
            status="pending_acknowledgement",
            escalated_at=escalated_at,
        )
        self._session.add(row)
        self._session.add(AuditEvent(
            id=str(uuid.uuid4()),
            event_id=event_id,
            action="escalated",
            actor=actor.email,
            actor_role=actor_role,
            occurred_at=escalated_at,
            details_json=json.dumps({
                "escalation_id": row.id,
                "destination": "shift_supervisor",
                "auto_created": True,
            }),
        ))
