"""AuditEvent model — immutable append-only audit trail."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.mixins import UUIDPrimaryKeyMixin

AUDIT_ACTIONS = (
    "event_received",
    "event_normalised",
    "assessment_started",
    "triage_completed",
    "context_retrieved",
    "evidence_retrieved",
    "risk_assessed",
    "confidence_assessed",
    "explanation_generated",
    "recommendation_created",
    "awaiting_human_review",
    "human_decision",
    "escalated",
    "dismissed",
    "closed",
    "feedback_submitted",
    "error",
    "status_changed",
    "override",
)


class AuditEvent(UUIDPrimaryKeyMixin, Base):
    """
    Immutable audit record. No updated_at — records are never modified.
    INSERT only. No UPDATE or DELETE APIs exist for this table.
    """

    __tablename__ = "audit_events"

    event_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("security_events.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    occurred_at: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    details_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    redacted: Mapped[bool] = mapped_column(default=False, nullable=False)

    event: Mapped[SecurityEvent | None] = relationship(  # type: ignore[name-defined]
        "SecurityEvent", back_populates="audit_events"
    )


if TYPE_CHECKING:
    from app.models.event import SecurityEvent
