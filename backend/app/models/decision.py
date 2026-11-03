"""OperatorDecision model — records human decisions on events."""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

DECISION_TYPES = (
    "accept",
    "reject",
    "dismiss",
    "request_context",
    "escalate",
    "override",
)


class OperatorDecision(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "operator_decisions"

    event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("security_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    recommendation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    decided_by: Mapped[str] = mapped_column(String(36), nullable=False, index=True)  # user_id
    decided_by_role: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_override: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    prior_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    risk_at_decision: Mapped[str | None] = mapped_column(String(16), nullable=True)
    confidence_at_decision: Mapped[float | None] = mapped_column(nullable=True)
    decided_at: Mapped[str] = mapped_column(String(32), nullable=False)  # ISO 8601 UTC

    event: Mapped[SecurityEvent] = relationship(  # noqa: F821
        "SecurityEvent", back_populates="operator_decisions"
    )

    from app.models.event import SecurityEvent  # noqa: F401, PLC0415
