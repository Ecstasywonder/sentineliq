"""Repositories for the event queue and incident-history retrieval.

These small repositories deliberately own only persistence concerns.  Services
remain responsible for scoring, lifecycle transitions, and audit decisions.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import SecurityEvent
from app.models.incident import IncidentHistory


class SecurityEventRepository:
    """Query and persist security events without leaking SQL into callers."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, event_id: str) -> SecurityEvent | None:
        return await self.session.get(SecurityEvent, event_id)

    async def find_recent_by_provider_id(
        self, provider_event_id: str, *, within_seconds: int
    ) -> SecurityEvent | None:
        result = await self.session.execute(
            select(SecurityEvent)
            .where(SecurityEvent.provider_event_id == provider_event_id)
            .order_by(SecurityEvent.created_at.desc())
            .limit(1)
        )
        event = result.scalar_one_or_none()
        if event is None or event.created_at is None:
            return None
        created_at = event.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        if (datetime.now(UTC) - created_at).total_seconds() <= within_seconds:
            return event
        return None

    async def add(self, event: SecurityEvent) -> SecurityEvent:
        self.session.add(event)
        await self.session.flush()
        return event


class IncidentRepository:
    """Read-focused historical incident repository used by contextual retrieval."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def by_location(self, location_id: str, *, limit: int = 20) -> list[IncidentHistory]:
        result = await self.session.execute(
            select(IncidentHistory)
            .where(IncidentHistory.location_id == location_id)
            .order_by(IncidentHistory.occurred_at.desc())
            .limit(limit)
        )
        return list(result.scalars())
