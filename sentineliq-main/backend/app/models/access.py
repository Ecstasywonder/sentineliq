"""AccessEvent model — badge/access-control events."""

from __future__ import annotations

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class AccessEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "access_events"

    location_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    facility_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    badge_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    person_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)  # non-PII reference
    access_type: Mapped[str] = mapped_column(String(32), nullable=False)  # entry/exit/denied
    access_granted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    occurred_at: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_system: Mapped[str] = mapped_column(String(64), default="mock", nullable=False)
    raw_data: Mapped[str | None] = mapped_column(String(512), nullable=True)
