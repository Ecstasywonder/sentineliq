"""IncidentHistory model — historical security incidents for retrieval."""

from __future__ import annotations

from sqlalchemy import Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class IncidentHistory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "incident_history"

    facility_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    location_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    incident_code: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    incident_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    occurred_at: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # Narrative text — used for semantic search (pgvector in production)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved: Mapped[bool] = mapped_column(default=False, nullable=False)
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Embedding stored as JSON array for MVP; replaced by vector column in production
    embedding_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    similarity_score: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )  # populated at query time
