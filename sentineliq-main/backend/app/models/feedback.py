"""Feedback model — operator feedback on recommendations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

OUTCOME_TYPES = (
    "confirmed_incident",
    "false_positive",
    "authorized_activity",
    "insufficient_information",
    "other",
)


class Feedback(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "feedback"

    event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("security_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    submitted_by: Mapped[str] = mapped_column(String(36), nullable=False)
    recommendation_useful: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    recommendation_accurate: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    missing_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[str] = mapped_column(String(32), nullable=False)

    event: Mapped[SecurityEvent] = relationship(  # type: ignore[name-defined]
        "SecurityEvent", back_populates="feedback"
    )


if TYPE_CHECKING:
    from app.models.event import SecurityEvent
