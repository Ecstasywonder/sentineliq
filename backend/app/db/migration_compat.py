"""Compatibility helpers that run before Alembic resolves the revision graph."""

from __future__ import annotations

from sqlalchemy import String, column, inspect, select, table
from sqlalchemy.engine import Connection

LEGACY_ASSESSMENT_REVISION = "0002_assessment_reconstruction_bundle"
ASSESSMENT_REVISION = "0002_assessment_bundle"


def remap_legacy_assessment_revision(connection: Connection) -> bool:
    """Remap the released over-length revision ID to its equivalent short ID.

    The migration body did not change when the revision identifier was shortened.
    This bootstrap must run before Alembic asks its revision map to resolve the
    database's current version. It is intentionally idempotent and supports a
    database that already contains the corrected identifier.
    """
    if not inspect(connection).has_table("alembic_version"):
        return False

    version_table = table("alembic_version", column("version_num", String(64)))
    installed = set(connection.execute(select(version_table.c.version_num)).scalars())
    if LEGACY_ASSESSMENT_REVISION not in installed:
        return False

    if ASSESSMENT_REVISION in installed:
        connection.execute(
            version_table.delete().where(version_table.c.version_num == LEGACY_ASSESSMENT_REVISION)
        )
    else:
        connection.execute(
            version_table.update()
            .where(version_table.c.version_num == LEGACY_ASSESSMENT_REVISION)
            .values(version_num=ASSESSMENT_REVISION)
        )
    return True
