"""Schedule model — employee and operational schedules."""

from __future__ import annotations

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

SCHEDULE_TYPES = ("employee", "maintenance", "delivery", "visitor", "facility", "other")


class Schedule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "schedules"

    facility_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    location_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    schedule_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    person_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_time: Mapped[str] = mapped_column(String(32), nullable=False)  # ISO 8601 UTC
    end_time: Mapped[str] = mapped_column(String(32), nullable=False)
    recurrence_rule: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    source_system: Mapped[str] = mapped_column(String(64), default="mock", nullable=False)
