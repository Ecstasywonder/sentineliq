"""
Tests for health and readiness endpoints.
These are the first passing tests for Gate 2.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "SentinelIQ"
    assert "version" in body


@pytest.mark.asyncio
async def test_health_includes_version(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == "0.1.0"


@pytest.mark.asyncio
async def test_app_info_endpoint(client: AsyncClient) -> None:
    response = await client.get("/api/v1/system/info")
    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "SentinelIQ"
    assert "environment" in body
    assert "features" in body


@pytest.mark.asyncio
async def test_security_headers_present(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("x-frame-options") == "DENY"
    assert response.headers.get("x-xss-protection") == "1; mode=block"


@pytest.mark.asyncio
async def test_openapi_schema_accessible(client: AsyncClient) -> None:
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "SentinelIQ API"


@pytest.mark.asyncio
async def test_docs_accessible_in_development(client: AsyncClient) -> None:
    response = await client.get("/docs")
    # In development, docs should return HTML (200) not 404
    assert response.status_code == 200
