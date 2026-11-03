"""Facility, Location, and Camera models."""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Facility(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "facilities"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    locations: Mapped[list[Location]] = relationship("Location", back_populates="facility")


class Location(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "locations"

    facility_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("facilities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    location_code: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    zone_type: Mapped[str] = mapped_column(String(64), nullable=False, default="standard")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    facility: Mapped[Facility] = relationship("Facility", back_populates="locations")
    cameras: Mapped[list[Camera]] = relationship("Camera", back_populates="location")


class Camera(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "cameras"

    location_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("locations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    camera_code: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    location: Mapped[Location] = relationship("Location", back_populates="cameras")
