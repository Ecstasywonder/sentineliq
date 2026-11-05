"""IntegrationHealth model — tracks evidence source availability."""

from __future__ import annotations

from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

INTEGRATION_STATUSES = ("healthy", "degraded", "unavailable", "unknown")


class IntegrationHealth(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "integration_health"

    source_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False, index=True)
    last_checked_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_successful_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    adapter_class: Mapped[str | None] = mapped_column(String(128), nullable=True)
