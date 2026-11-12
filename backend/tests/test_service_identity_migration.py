"""Contract tests for the unique service-purpose migration."""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


def _migration():
    path = Path(__file__).parents[1] / "alembic" / "versions" / "0006_unique_service_purpose.py"
    spec = importlib.util.spec_from_file_location("unique_service_purpose", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_is_linear_and_adds_unique_purpose(monkeypatch) -> None:
    migration = _migration()
    calls: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        migration.op,
        "create_unique_constraint",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    migration.upgrade()

    assert migration.down_revision == "0005_security_audit"
    assert calls == [(("uq_users_service_purpose", "users", ["service_purpose"]), {})]


@pytest.mark.asyncio
async def test_database_rejects_duplicate_service_purpose(
    db_session: AsyncSession,
) -> None:
    for suffix in ("one", "two"):
        db_session.add(
            User(
                id=str(uuid.uuid4()),
                email=f"orchestrate-{suffix}@service.test",
                full_name=f"Orchestrate {suffix}",
                hashed_password="not-used-by-service-identities",
                is_active=True,
                is_verified=True,
                service_purpose="orchestrate_tools",
            )
        )

    with pytest.raises(IntegrityError):
        await db_session.flush()
