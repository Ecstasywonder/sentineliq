"""
Mock AccessControlAdapter — returns synthetic badge events from the SQLite/Postgres
access_events table (seeded rows or empty list if none exist).

This is the mock implementation referenced by ADR-005; in production it would
be replaced by a concrete adapter that talks to the real access-control system.
"""

from __future__ import annotations

import time

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.base import AccessControlAdapter
from app.models.access import AccessEvent

logger = structlog.get_logger(__name__)

_SOURCE_ID = "mock_access_control"


class MockAccessControlAdapter(AccessControlAdapter):
    """Reads AccessEvent rows from the application database."""

    source_id = _SOURCE_ID

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_access_events(
        self,
        location_id: str,
        *,
        facility_id: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        stmt = (
            select(AccessEvent)
            .where(AccessEvent.location_id == location_id)
            .order_by(AccessEvent.occurred_at.desc())
            .limit(limit)
        )
        if facility_id:
            stmt = stmt.where(AccessEvent.facility_id == facility_id)

        result = await self._session.execute(stmt)
        rows = result.scalars().all()
        return [_row_to_dict(r) for r in rows]

    async def health_check(self) -> dict:
        t0 = time.monotonic()
        try:
            await self._session.execute(select(AccessEvent).limit(1))
            latency = round((time.monotonic() - t0) * 1000, 2)
            return {
                "source_id": self.source_id,
                "name": "MockAccessControl",
                "status": "healthy",
                "last_checked_at": None,
                "last_successful_at": None,
                "latency_ms": latency,
                "consecutive_failures": 0,
                "error_message": None,
                "adapter_class": f"{self.__class__.__module__}.{self.__class__.__name__}",
            }
        except Exception as exc:
            logger.warning("access_control_health_check_failed", error=str(exc))
            return {
                "source_id": self.source_id,
                "name": "MockAccessControl",
                "status": "unavailable",
                "last_checked_at": None,
                "last_successful_at": None,
                "latency_ms": None,
                "consecutive_failures": 1,
                "error_message": str(exc),
                "adapter_class": f"{self.__class__.__module__}.{self.__class__.__name__}",
            }


def _row_to_dict(row: AccessEvent) -> dict:
    return {
        "id": str(row.id),
        "location_id": row.location_id,
        "facility_id": row.facility_id,
        "badge_id": row.badge_id,
        "person_ref": row.person_ref,
        "access_type": row.access_type,
        "access_granted": row.access_granted,
        "occurred_at": row.occurred_at,
        "source_system": row.source_system,
    }
