"""SecurityEvent model — the central domain entity."""

from __future__ import annotations

from sqlalchemy import Float, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

# Valid event lifecycle statuses (see docs/architecture.md section 8)
EVENT_STATUSES = (
    "received",
    "normalised",
    "assessing",
    "awaiting_review",
    "context_incomplete",
    "dismissed",
    "escalated",
    "closed",
    "failed",
)

EVENT_TYPES = (
    "person_detected",
    "door_forced",
    "motion_detected",
    "badge_event",
    "delivery_detected",
    "vehicle_detected",
    "alarm_triggered",
    "other",
)


class SecurityEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "security_events"
    __table_args__ = (
        Index("ix_security_events_location_timestamp", "location_id", "event_timestamp"),
        Index("ix_security_events_status_risk", "status", "risk_level"),
    )

    # Source identifiers
    provider_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    source_adapter: Mapped[str] = mapped_column(String(64), default="simulator", nullable=False)

    # Event classification
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_timestamp: Mapped[str] = mapped_column(String(32), nullable=False)  # ISO 8601 UTC

    # Location
    location_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    facility_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    camera_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    zone: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Detection metadata
    detector_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    raw_metadata: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON

    # Normalised event data (JSON)
    normalised_data: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Lifecycle status
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="received", index=True)

    # Denormalised risk/confidence for fast queue queries
    risk_level: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_level: Mapped[str | None] = mapped_column(String(16), nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Assessment linkage
    agent_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # Relationships — use string references to avoid circular imports
    evidence: Mapped[list[EventEvidence]] = relationship(  # type: ignore[name-defined]
        "EventEvidence", back_populates="event", cascade="all, delete-orphan"
    )
    risk_assessment: Mapped[RiskAssessment | None] = relationship(  # type: ignore[name-defined]
        "RiskAssessment", back_populates="event", uselist=False
    )
    recommendation: Mapped[Recommendation | None] = relationship(  # type: ignore[name-defined]
        "Recommendation", back_populates="event", uselist=False
    )
    operator_decisions: Mapped[list[OperatorDecision]] = relationship(  # type: ignore[name-defined]
        "OperatorDecision", back_populates="event"
    )
    escalations: Mapped[list[Escalation]] = relationship(  # type: ignore[name-defined]
        "Escalation", back_populates="event"
    )
    audit_events: Mapped[list[AuditEvent]] = relationship(  # type: ignore[name-defined]
        "AuditEvent", back_populates="event"
    )
    feedback: Mapped[list[Feedback]] = relationship(  # type: ignore[name-defined]
        "Feedback", back_populates="event"
    )


# TYPE_CHECKING-only imports to satisfy type checkers without causing circular imports
from typing import TYPE_CHECKING  # noqa: E402

if TYPE_CHECKING:
    from app.models.assessment import RiskAssessment
    from app.models.audit import AuditEvent
    from app.models.decision import OperatorDecision
    from app.models.escalation import Escalation
    from app.models.evidence import EventEvidence
    from app.models.feedback import Feedback
    from app.models.recommendation import Recommendation
