"""PostgreSQL append-only audit migration contract tests."""

from __future__ import annotations

import importlib.util
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import psycopg2
import pytest


def _migration() -> ModuleType:
    path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "0005_service_identities_audit_guard.py"
    )
    spec = importlib.util.spec_from_file_location("security_audit_migration", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_is_linear_after_current_head() -> None:
    migration = _migration()
    assert migration.revision == "0005_security_audit"
    assert migration.down_revision == "0004_decision_snapshot"


def test_upgrade_installs_postgresql_audit_mutation_guards(monkeypatch) -> None:
    migration = _migration()
    statements: list[str] = []
    monkeypatch.setattr(migration.op, "add_column", lambda *args, **kwargs: None)
    monkeypatch.setattr(migration.op, "create_index", lambda *args, **kwargs: None)
    monkeypatch.setattr(migration.op, "create_check_constraint", lambda *args, **kwargs: None)
    monkeypatch.setattr(migration.op, "execute", statements.append)

    migration.upgrade()

    sql = "\n".join(statements).upper()
    assert "RETURNS TRIGGER" in sql
    assert "BEFORE UPDATE OR DELETE ON AUDIT_EVENTS" in sql
    assert "BEFORE TRUNCATE ON AUDIT_EVENTS" in sql
    assert "ERRCODE = '55000'" in sql
    assert "FOR EACH ROW" in sql
    assert "FOR EACH STATEMENT" in sql


def test_downgrade_removes_trigger_before_function(monkeypatch) -> None:
    migration = _migration()
    statements: list[str] = []
    monkeypatch.setattr(migration.op, "drop_index", lambda *args, **kwargs: None)
    monkeypatch.setattr(migration.op, "drop_column", lambda *args, **kwargs: None)
    monkeypatch.setattr(migration.op, "drop_constraint", lambda *args, **kwargs: None)
    monkeypatch.setattr(migration.op, "execute", statements.append)

    migration.downgrade()

    trigger_drops = [
        index for index, statement in enumerate(statements) if "DROP TRIGGER" in statement.upper()
    ]
    function_drop = next(
        index for index, statement in enumerate(statements) if "DROP FUNCTION" in statement.upper()
    )
    assert len(trigger_drops) == 2
    assert all(index < function_drop for index in trigger_drops)


@pytest.mark.parametrize(
    ("statement", "has_predicate"),
    [
        ("UPDATE audit_events SET redacted = TRUE", True),
        ("DELETE FROM audit_events", True),
        ("TRUNCATE TABLE audit_events", False),
    ],
)
def test_deployed_postgresql_rejects_audit_mutation(statement: str, has_predicate: bool) -> None:
    """Opt-in live PostgreSQL proof; every write is rolled back.

    Set ``AUDIT_GUARD_TEST_DSN`` to a migrated disposable/test database. The
    inserted row has no event FK and never commits.
    """
    dsn = os.getenv("AUDIT_GUARD_TEST_DSN")
    if not dsn:
        pytest.skip("AUDIT_GUARD_TEST_DSN is not configured")

    audit_id = str(uuid.uuid4())
    connection = psycopg2.connect(dsn)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO audit_events
                    (id, event_id, action, actor, actor_role, occurred_at, details_json, redacted)
                VALUES (%s, NULL, 'error', 'gate22-migration-test', NULL, %s, NULL, FALSE)
                """,
                (audit_id, datetime.now(UTC).isoformat()),
            )
            mutation_sql = f"{statement} WHERE id = %s" if has_predicate else statement
            mutation_params = (audit_id,) if has_predicate else None
            with pytest.raises(psycopg2.Error) as exc_info:
                cursor.execute(mutation_sql, mutation_params)
            assert exc_info.value.pgcode == "55000"
    finally:
        connection.rollback()
        connection.close()
