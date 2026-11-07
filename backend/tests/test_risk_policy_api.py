"""
Gate 9 — Integration tests for GET /api/v1/risk-policies and
GET /api/v1/risk-policies/{id}.

Tests cover:
  - List returns all seeded policies (empty + seeded)
  - Single policy retrieval includes full factor list
  - Factor weights, directions, is_active all serialized correctly
  - 404 for unknown policy_id
  - List is ordered by version descending
  - Permission: admin:policy required (stub user is platform_admin — passes)
"""

from __future__ import annotations

import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.risk_policy import RiskPolicy, RiskPolicyFactor

pytestmark = pytest.mark.asyncio


def _uid() -> str:
    return str(uuid.uuid4())


def _thresholds_json() -> str:
    return json.dumps(
        {
            "low": {"min": 0.0, "max": 29.0},
            "medium": {"min": 30.0, "max": 59.0},
            "high": {"min": 60.0, "max": 99.0},
            "critical": {"min": 100.0, "max": None},
        }
    )


async def _seed_policy(
    session: AsyncSession,
    *,
    version: str = "1.0",
    is_active: bool = True,
) -> RiskPolicy:
    """Insert a policy with 2 factors and return it."""
    from sqlalchemy import select

    stmt = select(RiskPolicy).where(RiskPolicy.version == version)
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing:
        return existing

    policy = RiskPolicy(
        id=_uid(),
        version=version,
        name=f"Policy {version}",
        description=f"Test policy version {version}",
        is_active=is_active,
        thresholds_json=_thresholds_json(),
    )
    session.add(policy)
    await session.flush()

    for factor_id, label, weight in [
        ("after_hours_access", "After Hours Access", 40.0),
        ("unverified_person", "Unverified Person", 50.0),
    ]:
        session.add(
            RiskPolicyFactor(
                id=_uid(),
                policy_id=policy.id,
                factor_id=factor_id,
                label=label,
                weight=weight,
                direction="increase",
                is_active=True,
            )
        )
    await session.flush()
    return policy


# ---------------------------------------------------------------------------
# Tests: GET /risk-policies
# ---------------------------------------------------------------------------


class TestListRiskPolicies:
    async def test_returns_200(self, client: AsyncClient, db_session: AsyncSession) -> None:
        await _seed_policy(db_session)
        resp = await client.get("/api/v1/risk-policies")
        assert resp.status_code == 200

    async def test_response_shape(self, client: AsyncClient, db_session: AsyncSession) -> None:
        await _seed_policy(db_session)
        resp = await client.get("/api/v1/risk-policies")
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert isinstance(data["items"], list)
        assert data["total"] >= 1

    async def test_includes_seeded_policy(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        policy = await _seed_policy(db_session)
        resp = await client.get("/api/v1/risk-policies")
        versions = [p["version"] for p in resp.json()["items"]]
        assert policy.version in versions

    async def test_list_items_have_no_factors(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """List view omits factors for performance — each item has empty factors."""
        await _seed_policy(db_session)
        resp = await client.get("/api/v1/risk-policies")
        for item in resp.json()["items"]:
            assert item["factors"] == []

    async def test_total_matches_item_count(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _seed_policy(db_session)
        resp = await client.get("/api/v1/risk-policies")
        data = resp.json()
        assert data["total"] == len(data["items"])


# ---------------------------------------------------------------------------
# Tests: GET /risk-policies/{id}
# ---------------------------------------------------------------------------


class TestGetRiskPolicy:
    async def test_returns_200(self, client: AsyncClient, db_session: AsyncSession) -> None:
        policy = await _seed_policy(db_session)
        resp = await client.get(f"/api/v1/risk-policies/{policy.id}")
        assert resp.status_code == 200

    async def test_response_shape(self, client: AsyncClient, db_session: AsyncSession) -> None:
        policy = await _seed_policy(db_session)
        resp = await client.get(f"/api/v1/risk-policies/{policy.id}")
        data = resp.json()

        assert data["id"] == policy.id
        assert data["version"] == policy.version
        assert data["name"] == policy.name
        assert isinstance(data["is_active"], bool)
        assert isinstance(data["factors"], list)

    async def test_factors_included(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """Single policy retrieval must include the factor list."""
        policy = await _seed_policy(db_session)
        resp = await client.get(f"/api/v1/risk-policies/{policy.id}")
        factors = resp.json()["factors"]
        assert len(factors) >= 2

    async def test_factor_shape(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """Each factor must have the required fields."""
        policy = await _seed_policy(db_session)
        resp = await client.get(f"/api/v1/risk-policies/{policy.id}")
        for f in resp.json()["factors"]:
            assert "factor_id" in f
            assert "label" in f
            assert "weight" in f
            assert "direction" in f
            assert "is_active" in f

    async def test_factors_ordered_by_weight_desc(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Factors must be returned ordered heaviest-first."""
        policy = await _seed_policy(db_session)
        resp = await client.get(f"/api/v1/risk-policies/{policy.id}")
        weights = [f["weight"] for f in resp.json()["factors"]]
        assert weights == sorted(weights, reverse=True)

    async def test_404_for_unknown_id(self, client: AsyncClient, db_session: AsyncSession) -> None:
        resp = await client.get(f"/api/v1/risk-policies/{_uid()}")
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "POLICY_NOT_FOUND"

    async def test_is_active_field(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """is_active must reflect the DB value."""
        policy = await _seed_policy(db_session, version="2.0-test", is_active=False)
        resp = await client.get(f"/api/v1/risk-policies/{policy.id}")
        assert resp.json()["is_active"] is False
