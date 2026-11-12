"""Enforce one service identity per machine purpose.

Revision ID: 0006_unique_service_purpose
Revises: 0005_security_audit
"""

from __future__ import annotations

from alembic import op

revision: str = "0006_unique_service_purpose"
down_revision: str | None = "0005_security_audit"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_users_service_purpose",
        "users",
        ["service_purpose"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_users_service_purpose", "users", type_="unique")
