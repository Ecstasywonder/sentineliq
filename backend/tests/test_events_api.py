"""
Event Ingestion API integration tests -- Gate 5.

Tests cover:
- POST /api/v1/events: happy path, validation errors, deduplication
- GET /api/v1/events: list, filtering, pagination
- GET /api/v1/events/{id}: found and not-found
- PATCH /api/v1/events/{id}/status: valid transition, invalid transition, 404
- Event lifecycle state machine: all valid and invalid transitions
- Schema validation: invalid event_type, missing required fields
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.models.event import SecurityEvent
from app.services.event_lifecycle import (
    InvalidTransitionError,
    allowed_transitions,
    is_terminal,
    validate_transition,
)

# ---------------------------------------------------------------------------
# Shared test payload
# ---------------------------------------------------------------------------

_BASE_PAYLOAD = {
    "event_type": "person_detected",
    "event_timestamp": "2026-11-03T22:30:00Z",
    "location_id": "LOADING_DOCK_3",
    "source_adapter": "simulator",
}


def _payload(**overrides) -> dict:
    return {**_BASE_PAYLOAD, **overrides}


# ===========================================================================
# POST /api/v1/events
# ===========================================================================


@pytest.mark.asyncio
async def test_ingest_event_happy_path(client: AsyncClient) -> None:
    """POST with valid payload returns 201 and a normalised event."""
    resp = await client.post("/api/v1/events", json=_payload())

    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "normalised"
    assert body["event_type"] == "person_detected"
    assert body["location_id"] == "LOADING_DOCK_3"
    assert "id" in body
    assert body["risk"]["score"] is None  # not yet assessed
    assert body["confidence"]["score"] is None


@pytest.mark.asyncio
async def test_ingest_returns_event_id(client: AsyncClient) -> None:
    """Returned event ID must be a non-empty string."""
    resp = await client.post("/api/v1/events", json=_payload())
    assert resp.status_code == 201
    assert len(resp.json()["id"]) > 0


@pytest.mark.asyncio
async def test_ingest_all_optional_fields(client: AsyncClient) -> None:
    """Optional fields are accepted and stored."""
    resp = await client.post(
        "/api/v1/events",
        json=_payload(
            provider_event_id="VMS-001",
            facility_id="fac-001",
            camera_id="CAM-DOCK-03",
            zone="restricted",
            detector_confidence=0.92,
            thumbnail_url="http://example.com/thumb.jpg",
            raw_metadata={"fps": 30, "resolution": "1080p"},
        ),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["camera_id"] == "CAM-DOCK-03"
    assert body["detector_confidence"] == pytest.approx(0.92)


@pytest.mark.asyncio
async def test_ingest_invalid_event_type(client: AsyncClient) -> None:
    """Unknown event_type returns 422."""
    resp = await client.post(
        "/api/v1/events",
        json=_payload(event_type="totally_unknown_type"),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_ingest_missing_required_location(client: AsyncClient) -> None:
    """Missing location_id returns 422."""
    payload = {
        "event_type": "person_detected",
        "event_timestamp": "2026-11-03T22:30:00Z",
    }
    resp = await client.post("/api/v1/events", json=payload)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_ingest_missing_required_timestamp(client: AsyncClient) -> None:
    """Missing event_timestamp returns 422."""
    payload = {
        "event_type": "person_detected",
        "location_id": "LOADING_DOCK_3",
    }
    resp = await client.post("/api/v1/events", json=payload)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_ingest_detector_confidence_out_of_range(client: AsyncClient) -> None:
    """detector_confidence > 1.0 returns 422."""
    resp = await client.post(
        "/api/v1/events",
        json=_payload(detector_confidence=1.5),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_ingest_deduplication_returns_200(client: AsyncClient) -> None:
    """
    Posting the same provider_event_id twice within the dedup window
    returns HTTP 200 (not 201) and the Duplicate-Event header.
    """
    pid = "VMS-DEDUP-001"

    first = await client.post("/api/v1/events", json=_payload(provider_event_id=pid))
    assert first.status_code == 201
    first_id = first.json()["id"]

    second = await client.post("/api/v1/events", json=_payload(provider_event_id=pid))
    assert second.status_code == 200
    assert second.headers.get("Duplicate-Event") == "true"
    # Returns the same event
    assert second.json()["id"] == first_id


@pytest.mark.asyncio
async def test_ingest_no_provider_id_never_deduplicates(client: AsyncClient) -> None:
    """Events without provider_event_id are always treated as new."""
    resp1 = await client.post("/api/v1/events", json=_payload())
    resp2 = await client.post("/api/v1/events", json=_payload())
    assert resp1.status_code == 201
    assert resp2.status_code == 201
    assert resp1.json()["id"] != resp2.json()["id"]


@pytest.mark.asyncio
async def test_ingest_all_valid_event_types(client: AsyncClient) -> None:
    """All defined event_type values are accepted."""
    from app.models.event import EVENT_TYPES

    for et in EVENT_TYPES:
        resp = await client.post("/api/v1/events", json=_payload(event_type=et))
        assert resp.status_code == 201, f"event_type '{et}' was rejected: {resp.text}"


# ===========================================================================
# GET /api/v1/events/{id}
# ===========================================================================


@pytest.mark.asyncio
async def test_get_event_by_id(client: AsyncClient) -> None:
    """Created event is retrievable by its ID."""
    create_resp = await client.post("/api/v1/events", json=_payload())
    event_id = create_resp.json()["id"]

    get_resp = await client.get(f"/api/v1/events/{event_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == event_id


@pytest.mark.asyncio
async def test_get_event_not_found(client: AsyncClient) -> None:
    """Non-existent event ID returns 404."""
    resp = await client.get("/api/v1/events/nonexistent-id-99999")
    assert resp.status_code == 404
    body = resp.json()
    # detail is a dict with code and message
    assert body["detail"]["code"] == "EVENT_NOT_FOUND"


# ===========================================================================
# GET /api/v1/events (list / queue)
# ===========================================================================


@pytest.mark.asyncio
async def test_list_events_returns_list(client: AsyncClient) -> None:
    """GET /api/v1/events returns a paginated list structure."""
    await client.post("/api/v1/events", json=_payload())
    resp = await client.get("/api/v1/events")
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert "total" in body
    assert "page" in body
    assert "pages" in body
    assert body["page"] == 1


@pytest.mark.asyncio
async def test_list_events_filter_by_status(client: AsyncClient) -> None:
    """status filter returns only matching events."""
    await client.post("/api/v1/events", json=_payload())
    resp = await client.get("/api/v1/events?status=normalised")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert all(item["status"] == "normalised" for item in items)


@pytest.mark.asyncio
async def test_list_events_invalid_status_returns_422(client: AsyncClient) -> None:
    """Unknown status filter value returns 422."""
    resp = await client.get("/api/v1/events?status=invalid_status_xyz")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_events_invalid_risk_level_returns_422(client: AsyncClient) -> None:
    """Unknown risk_level filter value returns 422."""
    resp = await client.get("/api/v1/events?risk_level=extreme")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_events_pagination(client: AsyncClient) -> None:
    """page and page_size parameters work correctly."""
    # Create 3 events
    for _ in range(3):
        await client.post("/api/v1/events", json=_payload())

    resp = await client.get("/api/v1/events?page=1&page_size=2")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) <= 2
    assert body["page_size"] == 2


@pytest.mark.asyncio
async def test_list_events_page_size_limit(client: AsyncClient) -> None:
    """page_size > 100 returns 422."""
    resp = await client.get("/api/v1/events?page_size=101")
    assert resp.status_code == 422


# ===========================================================================
# PATCH /api/v1/events/{id}/status
# ===========================================================================


@pytest.mark.asyncio
async def test_status_transition_valid(client: AsyncClient) -> None:
    """Valid transition normalised -> assessing succeeds."""
    create_resp = await client.post("/api/v1/events", json=_payload())
    event_id = create_resp.json()["id"]
    assert create_resp.json()["status"] == "normalised"

    patch_resp = await client.patch(
        f"/api/v1/events/{event_id}/status",
        json={"status": "assessing"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["status"] == "assessing"


@pytest.mark.asyncio
async def test_status_transition_invalid_returns_409(client: AsyncClient) -> None:
    """Invalid transition (normalised -> closed) returns 409."""
    create_resp = await client.post("/api/v1/events", json=_payload())
    event_id = create_resp.json()["id"]

    patch_resp = await client.patch(
        f"/api/v1/events/{event_id}/status",
        json={"status": "closed"},
    )
    assert patch_resp.status_code == 409
    assert patch_resp.json()["detail"]["code"] == "INVALID_TRANSITION"


@pytest.mark.asyncio
async def test_status_transition_unknown_status_returns_422(client: AsyncClient) -> None:
    """Unknown target status returns 422."""
    create_resp = await client.post("/api/v1/events", json=_payload())
    event_id = create_resp.json()["id"]

    patch_resp = await client.patch(
        f"/api/v1/events/{event_id}/status",
        json={"status": "unknown_status_xyz"},
    )
    assert patch_resp.status_code == 422


@pytest.mark.asyncio
async def test_status_transition_event_not_found(client: AsyncClient) -> None:
    """Transition on non-existent event returns 404."""
    resp = await client.patch(
        "/api/v1/events/no-such-event/status",
        json={"status": "assessing"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_status_transition_cannot_bypass_human_decision(
    client: AsyncClient, db_session
) -> None:
    event = SecurityEvent(
        id=str(uuid.uuid4()),
        provider_event_id=f"prov-{uuid.uuid4()}",
        source_adapter="simulator",
        event_type="motion_detected",
        event_timestamp="2026-11-03T10:00:00Z",
        location_id="loc-status-guard",
        status="awaiting_review",
    )
    db_session.add(event)
    await db_session.flush()

    resp = await client.patch(
        f"/api/v1/events/{event.id}/status",
        json={"status": "closed", "reason": "bypass attempt"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "DECISION_REQUIRED"
    await db_session.refresh(event)
    assert event.status == "awaiting_review"


# ===========================================================================
# Event lifecycle state machine unit tests (pure Python -- no HTTP)
# ===========================================================================


class TestEventLifecycle:
    def test_received_to_normalised_is_valid(self):
        validate_transition("received", "normalised")  # no exception

    def test_received_to_failed_is_valid(self):
        validate_transition("received", "failed")  # no exception

    def test_received_to_closed_is_invalid(self):
        with pytest.raises(InvalidTransitionError):
            validate_transition("received", "closed")

    def test_normalised_to_assessing_is_valid(self):
        validate_transition("normalised", "assessing")

    def test_assessing_to_awaiting_review_is_valid(self):
        validate_transition("assessing", "awaiting_review")

    def test_assessing_to_context_incomplete_is_valid(self):
        validate_transition("assessing", "context_incomplete")

    def test_awaiting_review_to_dismissed_is_valid(self):
        validate_transition("awaiting_review", "dismissed")

    def test_awaiting_review_to_closed_is_valid(self):
        validate_transition("awaiting_review", "closed")

    def test_awaiting_review_to_escalated_is_valid(self):
        validate_transition("awaiting_review", "escalated")

    def test_escalated_to_closed_is_valid(self):
        validate_transition("escalated", "closed")

    def test_closed_is_terminal(self):
        assert is_terminal("closed")
        with pytest.raises(InvalidTransitionError):
            validate_transition("closed", "normalised")

    def test_dismissed_is_terminal(self):
        assert is_terminal("dismissed")
        with pytest.raises(InvalidTransitionError):
            validate_transition("dismissed", "received")

    def test_failed_is_terminal(self):
        assert is_terminal("failed")
        with pytest.raises(InvalidTransitionError):
            validate_transition("failed", "assessing")

    def test_received_is_not_terminal(self):
        assert not is_terminal("received")

    def test_allowed_transitions_received(self):
        allowed = allowed_transitions("received")
        assert "normalised" in allowed
        assert "failed" in allowed
        assert "closed" not in allowed

    def test_allowed_transitions_terminal_empty(self):
        assert allowed_transitions("closed") == []
        assert allowed_transitions("dismissed") == []
        assert allowed_transitions("failed") == []

    def test_invalid_transition_error_message(self):
        exc = InvalidTransitionError("received", "closed")
        assert "received" in str(exc)
        assert "closed" in str(exc)
