"""Recommendation model."""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Recommendation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "recommendations"

    event_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("security_events.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_action: Mapped[str] = mapped_column(Text, nullable=False)
    why_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array of {text, evidence_ids}
    missing_evidence_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    limitations_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    requires_human_review: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    risk_score: Mapped[float] = mapped_column(nullable=False)
    confidence_score: Mapped[float] = mapped_column(nullable=False)
    agent_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    generated_at: Mapped[str] = mapped_column(String(32), nullable=False)

    event: Mapped[SecurityEvent] = relationship(  # noqa: F821
        "SecurityEvent", back_populates="recommendation"
    )

    from app.models.event import SecurityEvent  # noqa: F401, PLC0415
