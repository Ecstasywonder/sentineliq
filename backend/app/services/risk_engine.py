"""
Deterministic Risk Engine — Gate 4.

Computes a risk score from a set of active factor signals against a
versioned RiskPolicy stored in the database.

Key design constraints (ADR-003):
- The LLM NEVER produces or influences a risk score.
- All factors, weights, and thresholds are stored in the database.
- Every factor contribution is returned in the output for audit.
- Score is clamped to [0, 200] before level classification.
- Risk and Confidence are ALWAYS computed independently (ADR-004).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Public data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FactorSignal:
    """
    A single risk signal emitted by the evidence aggregation step.

    ``factor_id`` must match a ``RiskPolicyFactor.factor_id`` in the active
    policy.  If no matching factor is found the signal is silently ignored so
    that unknown factors never raise exceptions during live assessment.
    """

    factor_id: str
    triggered: bool  # True = factor applies to this event
    source: str = ""  # evidence source that produced this signal (for audit)


@dataclass
class FactorContribution:
    """A single factor's contribution to the final score (for the audit trail)."""

    factor_id: str
    label: str
    weight: float
    direction: str
    triggered: bool
    contribution: float  # weight applied (0.0 if not triggered)


@dataclass
class RiskResult:
    """
    Output of the Risk Engine.

    Consumers MUST persist ``factors_json`` to
    ``risk_assessments.risk_factors_json`` so the score is fully
    reproducible from the database record.
    """

    risk_score: float  # clamped, final score
    risk_level: str  # low | medium | high | critical
    policy_version: str
    factors: list[FactorContribution] = field(default_factory=list)

    @property
    def factors_json(self) -> str:
        """Serialised factor contributions for DB storage."""
        return json.dumps(
            [
                {
                    "factor_id": f.factor_id,
                    "label": f.label,
                    "weight": f.weight,
                    "direction": f.direction,
                    "triggered": f.triggered,
                    "contribution": f.contribution,
                }
                for f in self.factors
            ]
        )


# ---------------------------------------------------------------------------
# Threshold helpers
# ---------------------------------------------------------------------------

_DEFAULT_THRESHOLDS: dict[str, dict[str, float | None]] = {
    "low": {"min": 0.0, "max": 24.0},
    "medium": {"min": 25.0, "max": 49.0},
    "high": {"min": 50.0, "max": 74.0},
    "critical": {"min": 75.0, "max": None},
}


def _classify_risk(score: float, thresholds: dict) -> str:
    """Return the risk level string for a given score and threshold dict."""
    # Evaluate in severity order so the first match wins.
    for level in ("critical", "high", "medium", "low"):
        t = thresholds.get(level, {})
        lo: float = float(t.get("min", 0))
        hi: float | None = t.get("max")
        if hi is None:
            if score >= lo:
                return level
        else:
            if lo <= score <= float(hi):
                return level
    return "low"  # fallback — should not be reached with well-formed thresholds


# ---------------------------------------------------------------------------
# Risk Engine
# ---------------------------------------------------------------------------


class RiskEngine:
    """
    Stateless service that computes a deterministic risk score.

    Typical usage (inside an async route or service):

        engine = RiskEngine(db_session)
        result = await engine.assess(signals, policy_version="1.0")

    If no ``policy_version`` is given the engine falls back to the value in
    ``Settings.active_risk_policy_version``.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def assess(
        self,
        signals: list[FactorSignal],
        policy_version: str | None = None,
    ) -> RiskResult:
        """
        Compute a risk score for the supplied factor signals.

        Args:
            signals:        List of FactorSignal objects from the evidence layer.
            policy_version: Override the active policy version. If None, the
                            ``Settings.active_risk_policy_version`` is used.

        Returns:
            RiskResult with score, level, and per-factor breakdown.
        """
        from sqlalchemy import select

        from app.config import get_settings
        from app.models.risk_policy import RiskPolicy, RiskPolicyFactor

        if policy_version is None:
            policy_version = get_settings().active_risk_policy_version

        # ------------------------------------------------------------------
        # Load policy
        # ------------------------------------------------------------------
        stmt = select(RiskPolicy).where(RiskPolicy.version == policy_version)
        result = await self._session.execute(stmt)
        policy: RiskPolicy | None = result.scalar_one_or_none()

        if policy is None:
            logger.warning("risk_engine.policy_not_found", version=policy_version)
            return RiskResult(
                risk_score=0.0,
                risk_level="low",
                policy_version=policy_version,
                factors=[],
            )

        # ------------------------------------------------------------------
        # Load active factors
        # ------------------------------------------------------------------
        fstmt = select(RiskPolicyFactor).where(
            RiskPolicyFactor.policy_id == policy.id,
            RiskPolicyFactor.is_active.is_(True),
        )
        fresult = await self._session.execute(fstmt)
        db_factors: list[RiskPolicyFactor] = list(fresult.scalars().all())

        # Build lookups
        factor_map = {f.factor_id: f for f in db_factors}
        signal_map = {s.factor_id: s for s in signals}

        # ------------------------------------------------------------------
        # Score
        # ------------------------------------------------------------------
        contributions: list[FactorContribution] = []
        raw_score: float = 0.0

        for factor_id, db_factor in factor_map.items():
            signal = signal_map.get(factor_id)
            triggered = signal.triggered if signal is not None else False
            contribution = db_factor.weight if triggered else 0.0
            raw_score += contribution
            contributions.append(
                FactorContribution(
                    factor_id=factor_id,
                    label=db_factor.label,
                    weight=db_factor.weight,
                    direction=db_factor.direction,
                    triggered=triggered,
                    contribution=contribution,
                )
            )

        clamped = max(0.0, min(200.0, raw_score))

        # ------------------------------------------------------------------
        # Classify
        # ------------------------------------------------------------------
        try:
            thresholds = json.loads(policy.thresholds_json)
        except (json.JSONDecodeError, TypeError):
            logger.warning("risk_engine.invalid_thresholds_json", policy_id=policy.id)
            thresholds = _DEFAULT_THRESHOLDS

        level = _classify_risk(clamped, thresholds)

        logger.info(
            "risk_engine.assessed",
            policy_version=policy_version,
            raw_score=raw_score,
            clamped_score=clamped,
            risk_level=level,
            signals_received=len(signals),
            factors_triggered=sum(1 for c in contributions if c.triggered),
        )

        return RiskResult(
            risk_score=clamped,
            risk_level=level,
            policy_version=policy_version,
            factors=contributions,
        )
