"""RiskAssessment and ConfidenceAssessment models."""

from __future__ import annotations

from typing import TYPE_CHECKING

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
    risk_factors_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Confidence stored alongside risk but logically independent
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_level: Mapped[str | None] = mapped_column(String(16), nullable=True)
    confidence_reductions_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Immutable reconstruction bundle for the exact assessment run. These
    # snapshots keep operator-facing agent output and workflow context auditable
    # even when an event is later reprocessed or agent definitions change.
    triage_result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    context_result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation_result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_errors_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    workflow_state_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    assessed_at: Mapped[str] = mapped_column(String(32), nullable=False)
    agent_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    event: Mapped[SecurityEvent] = relationship(  # type: ignore[name-defined]
        "SecurityEvent", back_populates="risk_assessment"
    )


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
    reductions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    sources_available: Mapped[int] = mapped_column(default=0, nullable=False)
    sources_required: Mapped[int] = mapped_column(default=0, nullable=False)
    assessed_at: Mapped[str] = mapped_column(String(32), nullable=False)


if TYPE_CHECKING:
    from app.models.event import SecurityEvent
