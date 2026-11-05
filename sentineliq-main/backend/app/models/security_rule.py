"""SecurityRule model — facility and zone security rules."""

from __future__ import annotations

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class SecurityRule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "security_rules"

    facility_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    location_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    rule_code: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    rule_type: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    restricted_after: Mapped[str | None] = mapped_column(String(8), nullable=True)  # HH:MM
    restricted_before: Mapped[str | None] = mapped_column(String(8), nullable=True)
    applies_to_zones: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    effective_from: Mapped[str | None] = mapped_column(String(32), nullable=True)
    effective_until: Mapped[str | None] = mapped_column(String(32), nullable=True)
    policy_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
