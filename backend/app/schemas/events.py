"""
Pydantic schemas for the Event Ingestion API — Gate 5.

Separates transport layer (API contracts) from ORM models.
All timestamps are stored and returned as ISO 8601 UTC strings to avoid
timezone-handling inconsistencies across Python versions.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.config import get_settings
from app.models.event import EVENT_STATUSES, EVENT_TYPES
from app.security.metadata import sanitize_metadata

# ---------------------------------------------------------------------------
# Inbound
# ---------------------------------------------------------------------------

_EVENT_TYPES_SET = set(EVENT_TYPES)


class EventIngestRequest(BaseModel):
    """
    Payload for POST /api/v1/events.

    The detection system (or simulator) sends this when it detects an event.
    All fields are optional except event_type, event_timestamp, and location_id.
    """

    provider_event_id: str | None = Field(
        default=None,
        max_length=255,
        description="Upstream system's own ID — used for deduplication.",
    )
    source_adapter: str = Field(
        default="simulator",
        max_length=64,
        description="Adapter that produced this event.",
    )
    event_type: str = Field(
        ...,
        max_length=64,
        description=f"One of: {', '.join(sorted(EVENT_TYPES))}",
    )
    event_timestamp: str = Field(
        ...,
        max_length=32,
        description="ISO 8601 UTC timestamp of when the event occurred.",
    )
    location_id: str = Field(
        ...,
        max_length=128,
        description="Location code or ID where the event occurred.",
    )
    facility_id: str | None = Field(default=None, max_length=36)
    camera_id: str | None = Field(default=None, max_length=128)
    zone: str | None = Field(default=None, max_length=128)
    detector_confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Detection confidence from the upstream detector (0-1).",
    )
    thumbnail_url: str | None = Field(default=None, max_length=512)
    raw_metadata: dict[str, Any] | None = Field(
        default=None,
        description="Arbitrary metadata from the source system (stored as JSON).",
    )

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, v: str) -> str:
        if v not in _EVENT_TYPES_SET:
            raise ValueError(
                f"event_type '{v}' is not recognised. "
                f"Valid types: {sorted(_EVENT_TYPES_SET)}"
            )
        return v

    @field_validator("event_timestamp")
    @classmethod
    def validate_timestamp_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("event_timestamp must not be empty.")
        return v.strip()

    @field_validator("raw_metadata")
    @classmethod
    def validate_raw_metadata(
        cls,
        value: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if value is None:
            return None
        settings = get_settings()
        return sanitize_metadata(
            value,
            max_bytes=settings.event_raw_metadata_max_bytes,
            max_depth=settings.event_raw_metadata_max_depth,
            max_keys=settings.event_raw_metadata_max_keys,
            max_items=settings.event_raw_metadata_max_items,
            max_string_bytes=settings.event_raw_metadata_max_string_bytes,
        )


# ---------------------------------------------------------------------------
# Outbound — single event
# ---------------------------------------------------------------------------


class RiskSummary(BaseModel):
    score: float | None
    level: str | None


class ConfidenceSummary(BaseModel):
    score: float | None
    level: str | None


class EventResponse(BaseModel):
    """
    Response body for POST (201) and GET /api/v1/events/{id}.
    """

    id: str
    provider_event_id: str | None
    source_adapter: str
    event_type: str
    event_timestamp: str
    location_id: str
    facility_id: str | None
    camera_id: str | None
    zone: str | None
    detector_confidence: float | None
    thumbnail_url: str | None
    status: str
    risk: RiskSummary
    confidence: ConfidenceSummary
    agent_run_id: str | None
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_event(cls, event: object) -> EventResponse:
        """Build an EventResponse from a SecurityEvent ORM instance."""
        from app.models.event import SecurityEvent

        e: SecurityEvent = event  # type: ignore[assignment]
        return cls(
            id=e.id,
            provider_event_id=e.provider_event_id,
            source_adapter=e.source_adapter,
            event_type=e.event_type,
            event_timestamp=e.event_timestamp,
            location_id=e.location_id,
            facility_id=e.facility_id,
            camera_id=e.camera_id,
            zone=e.zone,
            detector_confidence=e.detector_confidence,
            thumbnail_url=e.thumbnail_url,
            status=e.status,
            risk=RiskSummary(score=e.risk_score, level=e.risk_level),
            confidence=ConfidenceSummary(
                score=e.confidence_score, level=e.confidence_level
            ),
            agent_run_id=e.agent_run_id,
            created_at=e.created_at.isoformat() if e.created_at else "",
            updated_at=e.updated_at.isoformat() if e.updated_at else "",
        )


# ---------------------------------------------------------------------------
# Outbound — list / queue
# ---------------------------------------------------------------------------


class EventListResponse(BaseModel):
    """Paginated event queue response."""

    items: list[EventResponse]
    total: int
    page: int
    page_size: int
    pages: int


# ---------------------------------------------------------------------------
# Error response
# ---------------------------------------------------------------------------


class ErrorDetail(BaseModel):
    code: str
    message: str
    detail: str | None = None


# ---------------------------------------------------------------------------
# Status constants re-exported for use in routers
# ---------------------------------------------------------------------------

VALID_STATUSES = set(EVENT_STATUSES)
