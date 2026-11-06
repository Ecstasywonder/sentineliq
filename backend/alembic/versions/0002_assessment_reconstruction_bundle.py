"""Persist the complete assessment reconstruction bundle.

Revision ID: 0002_assessment_reconstruction_bundle
Revises: 0001_initial_schema
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0002_assessment_reconstruction_bundle"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column("risk_assessments", sa.Column("triage_result_json", sa.Text(), nullable=True))
    op.add_column("risk_assessments", sa.Column("context_result_json", sa.Text(), nullable=True))
    op.add_column(
        "risk_assessments",
        sa.Column("explanation_result_json", sa.Text(), nullable=True),
    )
    op.add_column("risk_assessments", sa.Column("evidence_errors_json", sa.Text(), nullable=True))
    op.add_column("risk_assessments", sa.Column("workflow_state_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("risk_assessments", "workflow_state_json")
    op.drop_column("risk_assessments", "evidence_errors_json")
    op.drop_column("risk_assessments", "explanation_result_json")
    op.drop_column("risk_assessments", "context_result_json")
    op.drop_column("risk_assessments", "triage_result_json")
