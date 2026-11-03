"""
Mock ScheduleAdapter — reads Schedule rows from the application database.
"""

from __future__ import annotations

import time

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.base import ScheduleAdapter
from app.models.schedule import Schedule

logger = structlog.get_logger(__name__)

_SOURCE_ID = "mock_schedule"


class MockScheduleAdapter(ScheduleAdapter):
    """Reads Schedule rows from the application database."""

    source_id = _SOURCE_ID

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_schedule(
        self,
        location_id: str | None = None,
        *,
        facility_id: str | None = None,
        schedule_type: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        stmt = select(Schedule).where(Schedule.is_active.is_(True)).limit(limit)
        if location_id:
            stmt = stmt.where(Schedule.location_id == location_id)
        if facility_id:
            stmt = stmt.where(Schedule.facility_id == facility_id)
        if schedule_type:
            stmt = stmt.where(Schedule.schedule_type == schedule_type)

        result = await self._session.execute(stmt)
        rows = result.scalars().all()
        return [_row_to_dict(r) for r in rows]

    async def health_check(self) -> dict:
        t0 = time.monotonic()
        try:
            await self._session.execute(select(Schedule).limit(1))
            latency = round((time.monotonic() - t0) * 1000, 2)
            return {
                "source_id": self.source_id,
                "name": "MockSchedule",
                "status": "healthy",
                "last_checked_at": None,
                "last_successful_at": None,
                "latency_ms": latency,
                "consecutive_failures": 0,
                "error_message": None,
                "adapter_class": f"{self.__class__.__module__}.{self.__class__.__name__}",
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("schedule_health_check_failed", error=str(exc))
            return {
                "source_id": self.source_id,
                "name": "MockSchedule",
                "status": "unavailable",
                "last_checked_at": None,
                "last_successful_at": None,
                "latency_ms": None,
                "consecutive_failures": 1,
                "error_message": str(exc),
                "adapter_class": f"{self.__class__.__module__}.{self.__class__.__name__}",
            }


def _row_to_dict(row: Schedule) -> dict:
    return {
        "id": str(row.id),
        "facility_id": row.facility_id,
        "location_id": row.location_id,
        "schedule_type": row.schedule_type,
        "person_ref": row.person_ref,
        "description": row.description,
        "start_time": row.start_time,
        "end_time": row.end_time,
        "is_active": row.is_active,
        "source_system": row.source_system,
    }
