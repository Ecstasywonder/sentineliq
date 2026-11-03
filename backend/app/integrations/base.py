"""
Abstract base classes for SentinelIQ evidence adapters (ADR-005).

All concrete adapters — mock or real — must subclass the appropriate
abstract adapter so that the EvidenceAggregator can swap them without
changing any caller code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class BaseAdapter(ABC):
    """Minimum contract every adapter must satisfy."""

    #: Human-readable source identifier included in ToolMeta.source
    source_id: str = "unknown"

    async def health_check(self) -> dict:
        """
        Return a health dict compatible with IntegrationHealthRecord.

        Subclasses may override to perform a real probe; the default
        implementation returns ``status="unknown"``.
        """
        return {
            "source_id": self.source_id,
            "name": self.__class__.__name__,
            "status": "unknown",
            "last_checked_at": None,
            "last_successful_at": None,
            "latency_ms": None,
            "consecutive_failures": 0,
            "error_message": None,
            "adapter_class": f"{self.__class__.__module__}.{self.__class__.__name__}",
        }


class AccessControlAdapter(BaseAdapter):
    """Contract for badge/access-control data sources."""

    @abstractmethod
    async def get_access_events(
        self,
        location_id: str,
        *,
        facility_id: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Return raw access-event dicts for *location_id*."""


class ScheduleAdapter(BaseAdapter):
    """Contract for employee/operational schedule sources."""

    @abstractmethod
    async def get_schedule(
        self,
        location_id: str | None = None,
        *,
        facility_id: str | None = None,
        schedule_type: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Return raw schedule dicts."""


class WorkOrderAdapter(BaseAdapter):
    """Contract for work-order / maintenance sources."""

    @abstractmethod
    async def get_work_orders(
        self,
        location_id: str,
        *,
        facility_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Return raw work-order dicts for *location_id*."""


class DeliveryAdapter(BaseAdapter):
    """Contract for delivery-schedule sources."""

    @abstractmethod
    async def get_deliveries(
        self,
        location_id: str,
        *,
        facility_id: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Return raw delivery dicts for *location_id*."""
