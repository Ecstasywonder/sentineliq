"""Add purpose-bound service identities and enforce append-only audit events.

Revision ID: 0005_security_audit
Revises: 0004_decision_snapshot
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0005_security_audit"
down_revision: str | None = "0004_decision_snapshot"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("service_purpose", sa.String(length=64), nullable=True),
    )
    op.create_index("ix_users_service_purpose", "users", ["service_purpose"], unique=False)
    op.create_check_constraint(
        "ck_users_service_purpose",
        "users",
        "service_purpose IS NULL OR "
        "service_purpose IN ('orchestrate_tools', 'event_ingestion')",
    )

    # The application has no mutation API for audit rows, but database-level
    # enforcement also protects against bugs, maintenance scripts, and a
    # compromised application role. PostgreSQL raises SQLSTATE 55000.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_audit_event_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events is append-only; % is forbidden', TG_OP
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        DROP TRIGGER IF EXISTS audit_events_append_only ON audit_events
        """
    )
    op.execute(
        """
        DROP TRIGGER IF EXISTS audit_events_truncate_guard ON audit_events
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_events_append_only
        BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION reject_audit_event_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_events_truncate_guard
        BEFORE TRUNCATE ON audit_events
        FOR EACH STATEMENT EXECUTE FUNCTION reject_audit_event_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_events_append_only ON audit_events")
    op.execute("DROP TRIGGER IF EXISTS audit_events_truncate_guard ON audit_events")
    op.execute("DROP FUNCTION IF EXISTS reject_audit_event_mutation()")
    op.drop_constraint("ck_users_service_purpose", "users", type_="check")
    op.drop_index("ix_users_service_purpose", table_name="users")
    op.drop_column("users", "service_purpose")
