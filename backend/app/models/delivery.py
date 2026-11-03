"""Delivery model — scheduled and unscheduled deliveries."""

from __future__ import annotations

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Delivery(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "deliveries"

    facility_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    location_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    supplier_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    delivery_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    scheduled_start: Mapped[str] = mapped_column(String(32), nullable=False)
    scheduled_end: Mapped[str] = mapped_column(String(32), nullable=False)
    is_scheduled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_system: Mapped[str] = mapped_column(String(64), default="mock", nullable=False)
