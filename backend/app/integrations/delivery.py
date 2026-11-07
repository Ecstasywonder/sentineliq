"""
Mock DeliveryAdapter — reads Delivery rows from the application database.
"""

from __future__ import annotations

import time

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.base import DeliveryAdapter
from app.models.delivery import Delivery

logger = structlog.get_logger(__name__)

_SOURCE_ID = "mock_delivery"


class MockDeliveryAdapter(DeliveryAdapter):
    """Reads Delivery rows from the application database."""

    source_id = _SOURCE_ID

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_deliveries(
        self,
        location_id: str,
        *,
        facility_id: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        stmt = select(Delivery).where(Delivery.location_id == location_id).limit(limit)
        if facility_id:
            stmt = stmt.where(Delivery.facility_id == facility_id)

        result = await self._session.execute(stmt)
        rows = result.scalars().all()
        return [_row_to_dict(r) for r in rows]

    async def health_check(self) -> dict:
        t0 = time.monotonic()
        try:
            await self._session.execute(select(Delivery).limit(1))
            latency = round((time.monotonic() - t0) * 1000, 2)
            return {
                "source_id": self.source_id,
                "name": "MockDelivery",
                "status": "healthy",
                "last_checked_at": None,
                "last_successful_at": None,
                "latency_ms": latency,
                "consecutive_failures": 0,
                "error_message": None,
                "adapter_class": f"{self.__class__.__module__}.{self.__class__.__name__}",
            }
        except Exception as exc:
            logger.warning("delivery_health_check_failed", error=str(exc))
            return {
                "source_id": self.source_id,
                "name": "MockDelivery",
                "status": "unavailable",
                "last_checked_at": None,
                "last_successful_at": None,
                "latency_ms": None,
                "consecutive_failures": 1,
                "error_message": str(exc),
                "adapter_class": f"{self.__class__.__module__}.{self.__class__.__name__}",
            }


def _row_to_dict(row: Delivery) -> dict:
    return {
        "id": str(row.id),
        "facility_id": row.facility_id,
        "location_id": row.location_id,
        "supplier_name": row.supplier_name,
        "delivery_reference": row.delivery_reference,
        "scheduled_start": row.scheduled_start,
        "scheduled_end": row.scheduled_end,
        "is_scheduled": row.is_scheduled,
        "notes": row.notes,
        "source_system": row.source_system,
    }
