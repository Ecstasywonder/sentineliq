"""User, Role, and UserRole models."""

from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

VALID_ROLES = (
    "officer",
    "supervisor",
    "response_team",
    "facility_manager",
    "security_admin",
    "audit_reviewer",
    "platform_admin",
    "agent_admin",
    "agent_tool_reader",
    "event_ingestor",
)

SERVICE_ROLE_PURPOSES = {
    "agent_tool_reader": "orchestrate_tools",
    "event_ingestor": "event_ingestion",
}
SERVICE_ROLES = tuple(SERVICE_ROLE_PURPOSES)
HUMAN_ROLES = tuple(role for role in VALID_ROLES if role not in SERVICE_ROLES)


class Role(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "roles"

    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user_roles: Mapped[list[UserRole]] = relationship("UserRole", back_populates="role")


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "service_purpose IS NULL OR "
            "service_purpose IN ('orchestrate_tools', 'event_ingestion')",
            name="ck_users_service_purpose",
        ),
    )

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Null for interactive users. Machine identities are bound to one narrowly
    # scoped token purpose and cannot authenticate through the password flow.
    service_purpose: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    user_roles: Mapped[list[UserRole]] = relationship("UserRole", back_populates="user")


class UserRole(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_id", name="uq_user_role"),)

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    granted_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    user: Mapped[User] = relationship("User", back_populates="user_roles")
    role: Mapped[Role] = relationship("Role", back_populates="user_roles")
