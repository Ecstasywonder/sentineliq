"""Capture immutable decision-time recommendation snapshots.

Revision ID: 0004_decision_snapshot
Revises: 0003_refresh_token_rotation
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0004_decision_snapshot"
down_revision: str | None = "0003_refresh_token_rotation"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column(
        "operator_decisions",
        sa.Column("recommendation_snapshot", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("operator_decisions", "recommendation_snapshot")
