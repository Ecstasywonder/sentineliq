"""
Risk Engine tests -- Gate 4.

Tests cover:
- All five required demo scenarios (Scenarios A-E from the BRD)
- Zero-signal baseline
- Unknown signal ignored (no exception)
- Policy not found -> safe fallback
- Score clamping at upper bound
- factors_json serialisation round-trip
- _classify_risk with custom thresholds
"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.risk_policy import RiskPolicy, RiskPolicyFactor
from app.services.risk_engine import (
    FactorSignal,
    RiskEngine,
    RiskResult,
    _classify_risk,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _id() -> str:
    return str(uuid.uuid4())


_THRESHOLDS = json.dumps(
    {
        "low": {"min": 0, "max": 24},
        "medium": {"min": 25, "max": 49},
        "high": {"min": 50, "max": 74},
        "critical": {"min": 75, "max": None},
    }
)

# Default v1.0 factor definitions — mirrors seed data
_FACTORS = [
    {"factor_id": "no_matching_badge",   "label": "No matching authorised badge",     "weight": 25.0,  "direction": "increases_risk"},
    {"factor_id": "outside_schedule",    "label": "Activity outside permitted schedule", "weight": 20.0, "direction": "increases_risk"},
    {"factor_id": "restricted_area",     "label": "Restricted location at event time", "weight": 25.0, "direction": "increases_risk"},
    {"factor_id": "no_work_order",       "label": "No approved work order",           "weight": 15.0,  "direction": "increases_risk"},
    {"factor_id": "recent_incidents",    "label": "Relevant recent incidents",        "weight": 10.0,  "direction": "increases_risk"},
    {"factor_id": "forced_door_alarm",   "label": "Forced door or security alarm",    "weight": 40.0,  "direction": "increases_risk"},
    {"factor_id": "approved_maintenance","label": "Known approved maintenance",       "weight": -30.0, "direction": "decreases_risk"},
    {"factor_id": "valid_access_schedule","label": "Valid access and matching schedule","weight": -35.0,"direction": "decreases_risk"},
]


async def _seed_policy(session: AsyncSession, version: str = "1.0") -> RiskPolicy:
    """Insert a RiskPolicy + factors into the test DB and return the policy."""
    policy = RiskPolicy(
        id=_id(),
        version=version,
        name="Test Policy",
        is_active=True,
        thresholds_json=_THRESHOLDS,
    )
    session.add(policy)
    await session.flush()

    for f in _FACTORS:
        session.add(
            RiskPolicyFactor(
                id=_id(),
                policy_id=policy.id,
                is_active=True,
                **f,
            )
        )
    await session.flush()
    return policy


# ---------------------------------------------------------------------------
# _classify_risk unit tests (pure, no DB)
# ---------------------------------------------------------------------------

class TestClassifyRisk:
    def _thresholds(self) -> dict:
        return json.loads(_THRESHOLDS)

    def test_score_0_is_low(self):
        assert _classify_risk(0.0, self._thresholds()) == "low"

    def test_score_24_is_low(self):
        assert _classify_risk(24.0, self._thresholds()) == "low"

    def test_score_25_is_medium(self):
        assert _classify_risk(25.0, self._thresholds()) == "medium"

    def test_score_49_is_medium(self):
        assert _classify_risk(49.0, self._thresholds()) == "medium"

    def test_score_50_is_high(self):
        assert _classify_risk(50.0, self._thresholds()) == "high"

    def test_score_74_is_high(self):
        assert _classify_risk(74.0, self._thresholds()) == "high"

    def test_score_75_is_critical(self):
        assert _classify_risk(75.0, self._thresholds()) == "critical"

    def test_score_200_is_critical(self):
        assert _classify_risk(200.0, self._thresholds()) == "critical"

    def test_custom_thresholds(self):
        # Fully-specified threshold dict with all four levels
        custom = {
            "critical": {"min": 75, "max": None},
            "high":     {"min": 50, "max": 74},
            "medium":   {"min": 25, "max": 49},
            "low":      {"min": 0,  "max": 24},
        }
        assert _classify_risk(75.0, custom) == "critical"
        assert _classify_risk(50.0, custom) == "high"
        assert _classify_risk(25.0, custom) == "medium"
        assert _classify_risk(0.0,  custom) == "low"


# ---------------------------------------------------------------------------
# RiskEngine integration tests (async, uses db_session fixture from conftest)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_zero_signals_scores_zero(db_session: AsyncSession) -> None:
    """No signals triggered → score 0, level low."""
    await _seed_policy(db_session)
    engine = RiskEngine(db_session)
    result = await engine.assess(signals=[], policy_version="1.0")

    assert result.risk_score == 0.0
    assert result.risk_level == "low"
    assert result.policy_version == "1.0"
    assert len(result.factors) == len(_FACTORS)
    assert all(not f.triggered for f in result.factors)
    assert all(f.contribution == 0.0 for f in result.factors)


@pytest.mark.asyncio
async def test_scenario_a_authorised_activity(db_session: AsyncSession) -> None:
    """
    Scenario A — Authorised Activity (BRD §11).
    Valid badge + matching schedule → decreasing factors dominate.
    Expected: LOW risk (score ≤ 24).
    """
    await _seed_policy(db_session, version="1.0-a")
    engine = RiskEngine(db_session)

    signals = [
        FactorSignal("valid_access_schedule", triggered=True, source="access_control"),
        FactorSignal("approved_maintenance",  triggered=False),
    ]
    result = await engine.assess(signals, policy_version="1.0-a")

    # valid_access_schedule weight = -35; clamped at 0
    assert result.risk_score == 0.0
    assert result.risk_level == "low"

    triggered = {f.factor_id: f for f in result.factors if f.triggered}
    assert "valid_access_schedule" in triggered
    assert triggered["valid_access_schedule"].contribution == -35.0


@pytest.mark.asyncio
async def test_scenario_b_unverified_after_hours(db_session: AsyncSession) -> None:
    """
    Scenario B — Unverified After-Hours Event (BRD §11).
    No badge + outside schedule + restricted area → HIGH/CRITICAL.
    Expected: score ≥ 50.
    """
    await _seed_policy(db_session, version="1.0-b")
    engine = RiskEngine(db_session)

    signals = [
        FactorSignal("no_matching_badge", triggered=True, source="access_control"),
        FactorSignal("outside_schedule",  triggered=True, source="schedule"),
        FactorSignal("restricted_area",   triggered=True, source="policy"),
    ]
    result = await engine.assess(signals, policy_version="1.0-b")

    # 25 + 20 + 25 = 70 → HIGH
    assert result.risk_score == 70.0
    assert result.risk_level == "high"


@pytest.mark.asyncio
async def test_scenario_c_missing_evidence(db_session: AsyncSession) -> None:
    """
    Scenario C — Missing Evidence (BRD §11).
    Some factors cannot be evaluated — untriggered factors contribute 0.
    Score is based only on what IS known.
    """
    await _seed_policy(db_session, version="1.0-c")
    engine = RiskEngine(db_session)

    # Only forced_door_alarm is known
    signals = [
        FactorSignal("forced_door_alarm", triggered=True, source="detection_system"),
    ]
    result = await engine.assess(signals, policy_version="1.0-c")

    # 40 -> LOW boundary missed; 40 is between 25-49 -> MEDIUM
    assert result.risk_score == 40.0
    assert result.risk_level == "medium"


@pytest.mark.asyncio
async def test_scenario_d_critical_event(db_session: AsyncSession) -> None:
    """
    Scenario D — Multiple risk factors fired simultaneously → CRITICAL.
    """
    await _seed_policy(db_session, version="1.0-d")
    engine = RiskEngine(db_session)

    signals = [
        FactorSignal("no_matching_badge",  triggered=True),
        FactorSignal("outside_schedule",   triggered=True),
        FactorSignal("restricted_area",    triggered=True),
        FactorSignal("forced_door_alarm",  triggered=True),
        FactorSignal("recent_incidents",   triggered=True),
    ]
    result = await engine.assess(signals, policy_version="1.0-d")

    # 25 + 20 + 25 + 40 + 10 = 120 → CRITICAL
    assert result.risk_score == 120.0
    assert result.risk_level == "critical"


@pytest.mark.asyncio
async def test_scenario_e_ai_unavailable_deterministic_score(db_session: AsyncSession) -> None:
    """
    Scenario E — AI Unavailable (BRD §11).
    Risk Engine is deterministic so it works without LLM.
    Score must be correct regardless of AI availability.
    """
    await _seed_policy(db_session, version="1.0-e")
    engine = RiskEngine(db_session)

    signals = [
        FactorSignal("no_matching_badge", triggered=True),
        FactorSignal("outside_schedule",  triggered=True),
    ]
    result = await engine.assess(signals, policy_version="1.0-e")

    # 25 + 20 = 45 → MEDIUM
    assert result.risk_score == 45.0
    assert result.risk_level == "medium"
    # The result is fully formed without any LLM involvement
    assert result.policy_version == "1.0-e"


@pytest.mark.asyncio
async def test_unknown_signal_is_ignored(db_session: AsyncSession) -> None:
    """A signal whose factor_id is not in the policy must be silently dropped."""
    await _seed_policy(db_session, version="1.0-unk")
    engine = RiskEngine(db_session)

    signals = [
        FactorSignal("completely_unknown_factor", triggered=True),
    ]
    result = await engine.assess(signals, policy_version="1.0-unk")

    # Unknown signal contributes nothing
    assert result.risk_score == 0.0
    assert result.risk_level == "low"


@pytest.mark.asyncio
async def test_policy_not_found_returns_safe_fallback(db_session: AsyncSession) -> None:
    """When a policy version does not exist the engine returns score=0, level=low."""
    engine = RiskEngine(db_session)
    result = await engine.assess(
        signals=[FactorSignal("no_matching_badge", triggered=True)],
        policy_version="nonexistent-policy",
    )
    assert result.risk_score == 0.0
    assert result.risk_level == "low"
    assert result.factors == []


@pytest.mark.asyncio
async def test_score_clamped_at_upper_bound(db_session: AsyncSession) -> None:
    """Score cannot exceed 200 even if weights sum higher."""
    # Create a policy with factors summing to >200
    policy = RiskPolicy(
        id=_id(),
        version="1.0-clamp",
        name="Clamp Test",
        is_active=True,
        thresholds_json=_THRESHOLDS,
    )
    db_session.add(policy)
    await db_session.flush()

    for i in range(6):
        db_session.add(
            RiskPolicyFactor(
                id=_id(),
                policy_id=policy.id,
                factor_id=f"big_factor_{i}",
                label=f"Big Factor {i}",
                weight=50.0,
                direction="increases_risk",
                is_active=True,
            )
        )
    await db_session.flush()

    engine = RiskEngine(db_session)
    signals = [FactorSignal(f"big_factor_{i}", triggered=True) for i in range(6)]
    result = await engine.assess(signals, policy_version="1.0-clamp")

    # 6 x 50 = 300, clamped to 200
    assert result.risk_score == 200.0
    assert result.risk_level == "critical"


@pytest.mark.asyncio
async def test_factors_json_round_trip(db_session: AsyncSession) -> None:
    """factors_json must deserialise back to the same structure."""
    await _seed_policy(db_session, version="1.0-json")
    engine = RiskEngine(db_session)

    signals = [FactorSignal("no_matching_badge", triggered=True)]
    result = await engine.assess(signals, policy_version="1.0-json")

    parsed = json.loads(result.factors_json)
    assert isinstance(parsed, list)
    assert len(parsed) == len(_FACTORS)

    triggered_parsed = [f for f in parsed if f["triggered"]]
    assert len(triggered_parsed) == 1
    assert triggered_parsed[0]["factor_id"] == "no_matching_badge"
    assert triggered_parsed[0]["contribution"] == 25.0


@pytest.mark.asyncio
async def test_inactive_factor_excluded(db_session: AsyncSession) -> None:
    """Inactive policy factors must not contribute to the score."""
    policy = RiskPolicy(
        id=_id(),
        version="1.0-inactive",
        name="Inactive Factor Test",
        is_active=True,
        thresholds_json=_THRESHOLDS,
    )
    db_session.add(policy)
    await db_session.flush()

    # Active factor
    db_session.add(
        RiskPolicyFactor(
            id=_id(), policy_id=policy.id,
            factor_id="active_factor", label="Active",
            weight=30.0, direction="increases_risk", is_active=True,
        )
    )
    # Inactive factor — should be excluded
    db_session.add(
        RiskPolicyFactor(
            id=_id(), policy_id=policy.id,
            factor_id="inactive_factor", label="Inactive",
            weight=50.0, direction="increases_risk", is_active=False,
        )
    )
    await db_session.flush()

    engine = RiskEngine(db_session)
    signals = [
        FactorSignal("active_factor",   triggered=True),
        FactorSignal("inactive_factor", triggered=True),
    ]
    result = await engine.assess(signals, policy_version="1.0-inactive")

    # Only active factor contributes: 30
    assert result.risk_score == 30.0
    factor_ids = {f.factor_id for f in result.factors}
    assert "active_factor" in factor_ids
    assert "inactive_factor" not in factor_ids


@pytest.mark.asyncio
async def test_risk_and_confidence_independence(db_session: AsyncSession) -> None:
    """
    ADR-004 — Risk and Confidence are independent.
    High risk score must not imply any particular confidence level.
    This test verifies the Risk Engine produces a RiskResult with no
    confidence fields at all — confidence is computed separately.
    """
    await _seed_policy(db_session, version="1.0-indep")
    engine = RiskEngine(db_session)

    signals = [FactorSignal("forced_door_alarm", triggered=True)]
    result = await engine.assess(signals, policy_version="1.0-indep")

    # RiskResult has no confidence_score or confidence_level attribute
    assert not hasattr(result, "confidence_score")
    assert not hasattr(result, "confidence_level")
    assert isinstance(result, RiskResult)
