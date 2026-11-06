"""Focused tests for Gate 5-6 resource and privacy controls."""

from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.config import get_settings
from app.main import create_app
from app.schemas.events import EventIngestRequest
from app.security.metadata import REDACTED
from app.security.rate_limit import SlidingWindowRateLimiter


def _event(**overrides: object) -> EventIngestRequest:
    payload: dict[str, object] = {
        "event_type": "person_detected",
        "event_timestamp": "2026-11-06T10:00:00Z",
        "location_id": "LOADING_DOCK_3",
    }
    payload.update(overrides)
    return EventIngestRequest.model_validate(payload)


def test_raw_metadata_redacts_secrets_and_direct_identifiers() -> None:
    event = _event(
        raw_metadata={
            "sensor": "camera-7",
            "authorization": "Bearer do-not-store",
            "profile": {
                "customerEmail": "person@example.com",
                "phone_number": "+234000000000",
                "nationalId": "do-not-store-id",
                "refreshToken": "do-not-store-refresh",
                "status": "visitor",
            },
        }
    )

    assert event.raw_metadata == {
        "sensor": "camera-7",
        "authorization": REDACTED,
        "profile": {
            "customerEmail": REDACTED,
            "phone_number": REDACTED,
            "nationalId": REDACTED,
            "refreshToken": REDACTED,
            "status": "visitor",
        },
    }
    assert "do-not-store" not in json.dumps(event.raw_metadata)


def test_raw_metadata_rejects_oversized_string() -> None:
    settings = get_settings()
    with pytest.raises(ValidationError, match="maximum size"):
        _event(raw_metadata={"note": "x" * (settings.event_raw_metadata_max_string_bytes + 1)})


def test_raw_metadata_rejects_excessive_nesting() -> None:
    settings = get_settings()
    value: dict[str, object] = {"leaf": True}
    for index in range(settings.event_raw_metadata_max_depth + 1):
        value = {f"level_{index}": value}
    with pytest.raises(ValidationError, match="maximum depth"):
        _event(raw_metadata=value)


@pytest.mark.asyncio
async def test_sliding_window_limiter_blocks_and_recovers() -> None:
    limiter = SlidingWindowRateLimiter(window_seconds=60)

    first = await limiter.check("api", "peer:test", 2, now=100.0)
    second = await limiter.check("api", "peer:test", 2, now=101.0)
    blocked = await limiter.check("api", "peer:test", 2, now=102.0)
    recovered = await limiter.check("api", "peer:test", 2, now=161.1)

    assert first.allowed and first.remaining == 1
    assert second.allowed and second.remaining == 0
    assert not blocked.allowed and blocked.retry_after == 58
    assert recovered.allowed


@pytest.mark.asyncio
async def test_api_middleware_returns_429() -> None:
    settings = get_settings()
    original_api_limit = settings.rate_limit_api_per_minute
    original_auth_limit = settings.rate_limit_auth_per_minute
    original_enabled = settings.enable_rate_limiting
    try:
        settings.enable_rate_limiting = True
        settings.rate_limit_api_per_minute = 1
        settings.rate_limit_auth_per_minute = 10
        isolated_app = create_app()
        async with AsyncClient(
            transport=ASGITransport(app=isolated_app),
            base_url="http://rate-limit-test",
        ) as client:
            # A non-existent route exercises middleware without needing a DB.
            first = await client.get("/api/v1/rate-limit-probe")
            second = await client.get("/api/v1/rate-limit-probe")
        assert first.status_code != 429
        assert second.status_code == 429
        assert second.headers["retry-after"]
        assert second.json()["detail"]["code"] == "RATE_LIMITED"
    finally:
        settings.enable_rate_limiting = original_enabled
        settings.rate_limit_api_per_minute = original_api_limit
        settings.rate_limit_auth_per_minute = original_auth_limit


@pytest.mark.asyncio
async def test_request_body_ceiling_returns_413() -> None:
    settings = get_settings()
    original_limit = settings.max_request_body_bytes
    try:
        settings.max_request_body_bytes = 1_024
        isolated_app = create_app()
        async with AsyncClient(
            transport=ASGITransport(app=isolated_app),
            base_url="http://body-limit-test",
        ) as client:
            response = await client.post(
                "/api/v1/auth/token",
                content=b"x" * 1_025,
                headers={"content-type": "application/json"},
            )
        assert response.status_code == 413
        assert response.json()["detail"]["code"] == "REQUEST_TOO_LARGE"
    finally:
        settings.max_request_body_bytes = original_limit


@pytest.mark.asyncio
async def test_chunked_request_body_ceiling_returns_413() -> None:
    settings = get_settings()
    original_limit = settings.max_request_body_bytes

    async def oversized_chunks():
        yield b"x" * 600
        yield b"y" * 600

    try:
        settings.max_request_body_bytes = 1_024
        isolated_app = create_app()
        async with AsyncClient(
            transport=ASGITransport(app=isolated_app),
            base_url="http://chunked-body-limit-test",
        ) as client:
            response = await client.post(
                "/api/v1/auth/token",
                content=oversized_chunks(),
                headers={"content-type": "application/json"},
            )
        assert response.status_code == 413
        assert response.json()["detail"]["code"] == "REQUEST_TOO_LARGE"
    finally:
        settings.max_request_body_bytes = original_limit
