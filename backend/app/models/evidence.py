"""EventEvidence model — evidence items linked to a security event."""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

EVIDENCE_STATUSES = ("verified", "unavailable", "stale", "error", "partial")
EVIDENCE_SOURCE_TYPES = ("structured", "semantic", "document", "system")


class EventEvidence(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "event_evidence"

    event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("security_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    evidence_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), default="structured", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="verified", nullable=False)
    retrieved_at: Mapped[str] = mapped_column(String(32), nullable=False)  # ISO 8601 UTC
    source_timestamp: Mapped[str | None] = mapped_column(String(32), nullable=True)
    relevance: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # structured payload
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    event: Mapped[SecurityEvent] = relationship(  # noqa: F821
        "SecurityEvent", back_populates="evidence"
    )

    from app.models.event import SecurityEvent  # noqa: F401, PLC0415
