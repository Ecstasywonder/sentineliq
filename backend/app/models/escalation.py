"""Escalation model."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

ESCALATION_STATUSES = ("pending_acknowledgement", "acknowledged", "resolved", "cancelled")
ESCALATION_DESTINATIONS = ("shift_supervisor", "response_team", "security_admin", "external")


class Escalation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "escalations"

    event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("security_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    escalated_by: Mapped[str] = mapped_column(String(36), nullable=False)
    escalated_by_role: Mapped[str] = mapped_column(String(64), nullable=False)
    destination: Mapped[str] = mapped_column(String(64), nullable=False)
    priority: Mapped[str] = mapped_column(String(16), default="high", nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), default="pending_acknowledgement", nullable=False
    )
    acknowledged_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    acknowledged_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    escalated_at: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_snapshot_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommendation_snapshot_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    event: Mapped[SecurityEvent] = relationship(  # type: ignore[name-defined]
        "SecurityEvent", back_populates="escalations"
    )


if TYPE_CHECKING:
    from app.models.event import SecurityEvent
