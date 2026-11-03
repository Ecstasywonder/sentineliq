"""RiskPolicy and RiskPolicyFactor models."""

from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class RiskPolicy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "risk_policies"

    version: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    effective_from: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Threshold JSON: {"low": [0,24], "medium": [25,49], "high": [50,74], "critical": [75, null]}
    thresholds_json: Mapped[str] = mapped_column(Text, nullable=False)

    factors: Mapped[list[RiskPolicyFactor]] = relationship(
        "RiskPolicyFactor", back_populates="policy", cascade="all, delete-orphan"
    )


class RiskPolicyFactor(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "risk_policy_factors"

    policy_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("risk_policies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    factor_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    direction: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # increases_risk / decreases_risk
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    policy: Mapped[RiskPolicy] = relationship("RiskPolicy", back_populates="factors")
