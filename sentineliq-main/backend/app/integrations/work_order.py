"""
Mock WorkOrderAdapter — reads WorkOrder rows from the application database.
"""

from __future__ import annotations

import time

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.base import WorkOrderAdapter
from app.models.work_order import WorkOrder

logger = structlog.get_logger(__name__)

_SOURCE_ID = "mock_work_order"


class MockWorkOrderAdapter(WorkOrderAdapter):
    """Reads WorkOrder rows from the application database."""

    source_id = _SOURCE_ID

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_work_orders(
        self,
        location_id: str,
        *,
        facility_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        stmt = (
            select(WorkOrder)
            .where(WorkOrder.location_id == location_id)
            .limit(limit)
        )
        if facility_id:
            stmt = stmt.where(WorkOrder.facility_id == facility_id)
        if status:
            stmt = stmt.where(WorkOrder.status == status)

        result = await self._session.execute(stmt)
        rows = result.scalars().all()
        return [_row_to_dict(r) for r in rows]

    async def health_check(self) -> dict:
        t0 = time.monotonic()
        try:
            await self._session.execute(select(WorkOrder).limit(1))
            latency = round((time.monotonic() - t0) * 1000, 2)
            return {
                "source_id": self.source_id,
                "name": "MockWorkOrder",
                "status": "healthy",
                "last_checked_at": None,
                "last_successful_at": None,
                "latency_ms": latency,
                "consecutive_failures": 0,
                "error_message": None,
                "adapter_class": f"{self.__class__.__module__}.{self.__class__.__name__}",
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("work_order_health_check_failed", error=str(exc))
            return {
                "source_id": self.source_id,
                "name": "MockWorkOrder",
                "status": "unavailable",
                "last_checked_at": None,
                "last_successful_at": None,
                "latency_ms": None,
                "consecutive_failures": 1,
                "error_message": str(exc),
                "adapter_class": f"{self.__class__.__module__}.{self.__class__.__name__}",
            }


def _row_to_dict(row: WorkOrder) -> dict:
    return {
        "id": str(row.id),
        "facility_id": row.facility_id,
        "location_id": row.location_id,
        "work_order_number": row.work_order_number,
        "description": row.description,
        "assigned_to": row.assigned_to,
        "scheduled_start": row.scheduled_start,
        "scheduled_end": row.scheduled_end,
        "status": row.status,
        "requires_after_hours": row.requires_after_hours,
        "approved_by": row.approved_by,
        "source_system": row.source_system,
    }
