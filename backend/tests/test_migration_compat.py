"""Regression tests for released Alembic revision identifier compatibility."""

from __future__ import annotations

from sqlalchemy import Column, MetaData, String, Table, create_engine, select

from app.db.migration_compat import (
    ASSESSMENT_REVISION,
    LEGACY_ASSESSMENT_REVISION,
    remap_legacy_assessment_revision,
)


def _version_table(metadata: MetaData) -> Table:
    return Table(
        "alembic_version",
        metadata,
        Column("version_num", String(64), primary_key=True),
    )


def test_remaps_released_legacy_assessment_revision_before_alembic_resolution() -> None:
    engine = create_engine("sqlite://")
    metadata = MetaData()
    version_table = _version_table(metadata)
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(version_table.insert().values(version_num=LEGACY_ASSESSMENT_REVISION))
        assert remap_legacy_assessment_revision(connection) is True
        assert connection.scalar(select(version_table.c.version_num)) == ASSESSMENT_REVISION
        assert remap_legacy_assessment_revision(connection) is False
    engine.dispose()


def test_fresh_database_without_version_table_needs_no_remap() -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        assert remap_legacy_assessment_revision(connection) is False
    engine.dispose()


def test_remap_discards_duplicate_legacy_stamp_when_corrected_stamp_exists() -> None:
    engine = create_engine("sqlite://")
    metadata = MetaData()
    version_table = _version_table(metadata)
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            version_table.insert(),
            [
                {"version_num": LEGACY_ASSESSMENT_REVISION},
                {"version_num": ASSESSMENT_REVISION},
            ],
        )
        assert remap_legacy_assessment_revision(connection) is True
        assert set(connection.execute(select(version_table.c.version_num)).scalars()) == {
            ASSESSMENT_REVISION
        }
    engine.dispose()
