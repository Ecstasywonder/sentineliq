"""RiskAssessment and ConfidenceAssessment models."""

from __future__ import annotations

from sqlalchemy import Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

RISK_LEVELS = ("low", "medium", "high", "critical")
CONFIDENCE_LEVELS = ("low", "medium", "high")


class RiskAssessment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "risk_assessments"

    event_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("security_events.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    risk_policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    risk_score: Mapped[float] = mapped_column(Float, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    risk_factors_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array

    # Confidence stored alongside risk but logically independent
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_level: Mapped[str | None] = mapped_column(String(16), nullable=True)
    confidence_reductions_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    assessed_at: Mapped[str] = mapped_column(String(32), nullable=False)  # ISO 8601 UTC
    agent_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    event: Mapped[SecurityEvent] = relationship(  # noqa: F821
        "SecurityEvent", back_populates="risk_assessment"
    )

    from app.models.event import SecurityEvent  # noqa: F401, PLC0415


class ConfidenceAssessment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Separate confidence record for detailed audit trail.
    The summary is also denormalised onto RiskAssessment for query convenience.
    """

    __tablename__ = "confidence_assessments"

    event_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("security_events.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    confidence_level: Mapped[str] = mapped_column(String(16), nullable=False)
    reductions_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array
    sources_available: Mapped[int] = mapped_column(default=0, nullable=False)
    sources_required: Mapped[int] = mapped_column(default=0, nullable=False)
    assessed_at: Mapped[str] = mapped_column(String(32), nullable=False)
