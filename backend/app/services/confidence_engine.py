"""
Deterministic Confidence Engine — Gate 4.

Computes a confidence score representing how well-evidenced the risk
assessment is.  Confidence is ALWAYS independent from risk (ADR-004).

Key design constraints:
- Confidence starts at 1.0 (100 %).
- Each reduction factor that applies subtracts from the score.
- Score is clamped to [0.0, 1.0].
- Missing evidence = reduced confidence, NOT increased risk.
- The LLM never influences the confidence score directly; it may contribute
  an 'llm_unavailable' reduction if the explanation step fails.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum


# ---------------------------------------------------------------------------
# Reduction catalogue
# ---------------------------------------------------------------------------


class ConfidenceReduction(str, Enum):
    """
    Enumeration of all defined confidence reduction reasons.

    Values are the canonical ``reason`` strings stored in the DB and returned
    to callers.  Do NOT rename existing values — they appear in the audit trail.
    """

    SOURCE_UNAVAILABLE = "source_unavailable"
    SOURCE_STALE = "source_stale"
    CONTRADICTORY_EVIDENCE = "contradictory_evidence"
    INCOMPLETE_EVENT_METADATA = "incomplete_event_metadata"
    TOOL_RETRIEVAL_ERROR = "tool_retrieval_error"
    LLM_UNAVAILABLE = "llm_unavailable"


# Default reduction amounts per reason (fraction of 1.0)
_REDUCTION_AMOUNTS: dict[ConfidenceReduction, float] = {
    ConfidenceReduction.SOURCE_UNAVAILABLE: 0.20,
    ConfidenceReduction.SOURCE_STALE: 0.10,
    ConfidenceReduction.CONTRADICTORY_EVIDENCE: 0.15,
    ConfidenceReduction.INCOMPLETE_EVENT_METADATA: 0.10,
    ConfidenceReduction.TOOL_RETRIEVAL_ERROR: 0.10,
    ConfidenceReduction.LLM_UNAVAILABLE: 0.20,
}


# ---------------------------------------------------------------------------
# Input / output types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceStatus:
    """
    Represents the availability status of a single evidence source.

    ``source_id`` should match a value in ``integration_health.source_id``
    (e.g. ``"access_control"``, ``"schedule"``).
    """

    source_id: str
    available: bool
    stale: bool = False   # True if data is older than the configured freshness window
    required: bool = True  # False for optional sources whose absence is less significant


@dataclass(frozen=True)
class ConfidenceReductionRecord:
    """A single applied reduction, serialised to the DB."""

    reason: str       # ConfidenceReduction value
    amount: float
    source_id: str = ""  # populated when reason is source-specific
    detail: str = ""     # free-form detail for audit


@dataclass
class ConfidenceResult:
    """
    Output of the Confidence Engine.

    Consumers MUST persist ``reductions_json`` to
    ``confidence_assessments.reductions_json`` for audit.
    """

    confidence_score: float   # clamped [0.0, 1.0]
    confidence_level: str     # high | medium | low
    reductions: list[ConfidenceReductionRecord] = field(default_factory=list)
    sources_available: int = 0
    sources_required: int = 0

    @property
    def reductions_json(self) -> str:
        """Serialised reductions for DB storage."""
        return json.dumps(
            [
                {
                    "reason": r.reason,
                    "amount": r.amount,
                    "source_id": r.source_id,
                    "detail": r.detail,
                }
                for r in self.reductions
            ]
        )


# ---------------------------------------------------------------------------
# Confidence level classification
# ---------------------------------------------------------------------------

# (threshold, level) — evaluated highest-first; first match wins
_CONFIDENCE_THRESHOLDS: list[tuple[float, str]] = [
    (0.80, "high"),
    (0.50, "medium"),
    (0.00, "low"),
]


def _classify_confidence(score: float) -> str:
    for threshold, level in _CONFIDENCE_THRESHOLDS:
        if score >= threshold:
            return level
    return "low"


# ---------------------------------------------------------------------------
# Confidence Engine
# ---------------------------------------------------------------------------


class ConfidenceEngine:
    """
    Stateless service that computes a deterministic confidence score.

    This engine does NOT require a DB session because confidence reduction
    rules are defined as code constants (``_REDUCTION_AMOUNTS``), not rows.
    The thresholds are kept as code so they can be changed via a release
    without a migration — appropriate for operational parameters, not policy.

    Typical usage:

        engine = ConfidenceEngine()
        result = engine.assess(
            sources=sources,
            has_contradictory_evidence=False,
            incomplete_event_metadata=False,
            tool_retrieval_errors=[],
            llm_unavailable=False,
        )
    """

    def __init__(
        self,
        reduction_amounts: dict[ConfidenceReduction, float] | None = None,
    ) -> None:
        """
        Args:
            reduction_amounts: Override default reduction amounts (for testing
                               or calibration).  Unspecified reasons keep
                               their defaults.
        """
        self._amounts = {**_REDUCTION_AMOUNTS, **(reduction_amounts or {})}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def assess(
        self,
        sources: list[SourceStatus],
        has_contradictory_evidence: bool = False,
        incomplete_event_metadata: bool = False,
        tool_retrieval_errors: list[str] | None = None,
        llm_unavailable: bool = False,
    ) -> ConfidenceResult:
        """
        Compute a confidence score.

        Args:
            sources:
                All evidence sources that were attempted (both available and
                unavailable).
            has_contradictory_evidence:
                True if two or more evidence items contradict each other.
            incomplete_event_metadata:
                True if the incoming security event was missing required fields
                (e.g. no location_id, no timestamp).
            tool_retrieval_errors:
                List of source_ids where a tool call raised an exception (as
                opposed to a clean "source unavailable" response).
            llm_unavailable:
                True if the Explanation Agent could not produce an explanation.

        Returns:
            ConfidenceResult with clamped score, level, and per-reduction
            audit trail.
        """
        tool_errors = set(tool_retrieval_errors or [])
        reductions: list[ConfidenceReductionRecord] = []
        score: float = 1.0

        # ---- 1. Unavailable required sources --------------------------------
        for src in sources:
            if not src.available and src.required:
                amount = self._amounts[ConfidenceReduction.SOURCE_UNAVAILABLE]
                score -= amount
                reductions.append(
                    ConfidenceReductionRecord(
                        reason=ConfidenceReduction.SOURCE_UNAVAILABLE.value,
                        amount=amount,
                        source_id=src.source_id,
                        detail=f"Source '{src.source_id}' was unavailable during assessment.",
                    )
                )

        # ---- 2. Stale sources -----------------------------------------------
        for src in sources:
            if src.available and src.stale:
                amount = self._amounts[ConfidenceReduction.SOURCE_STALE]
                score -= amount
                reductions.append(
                    ConfidenceReductionRecord(
                        reason=ConfidenceReduction.SOURCE_STALE.value,
                        amount=amount,
                        source_id=src.source_id,
                        detail=f"Source '{src.source_id}' data was stale.",
                    )
                )

        # ---- 3. Contradictory evidence --------------------------------------
        if has_contradictory_evidence:
            amount = self._amounts[ConfidenceReduction.CONTRADICTORY_EVIDENCE]
            score -= amount
            reductions.append(
                ConfidenceReductionRecord(
                    reason=ConfidenceReduction.CONTRADICTORY_EVIDENCE.value,
                    amount=amount,
                    detail="Contradictory evidence items detected.",
                )
            )

        # ---- 4. Incomplete event metadata -----------------------------------
        if incomplete_event_metadata:
            amount = self._amounts[ConfidenceReduction.INCOMPLETE_EVENT_METADATA]
            score -= amount
            reductions.append(
                ConfidenceReductionRecord(
                    reason=ConfidenceReduction.INCOMPLETE_EVENT_METADATA.value,
                    amount=amount,
                    detail="Security event was missing required metadata fields.",
                )
            )

        # ---- 5. Tool retrieval errors (distinct from clean unavailability) --
        for source_id in sorted(tool_errors):  # sorted for deterministic order
            amount = self._amounts[ConfidenceReduction.TOOL_RETRIEVAL_ERROR]
            score -= amount
            reductions.append(
                ConfidenceReductionRecord(
                    reason=ConfidenceReduction.TOOL_RETRIEVAL_ERROR.value,
                    amount=amount,
                    source_id=source_id,
                    detail=f"Tool retrieval raised an error for source '{source_id}'.",
                )
            )

        # ---- 6. LLM unavailable ---------------------------------------------
        if llm_unavailable:
            amount = self._amounts[ConfidenceReduction.LLM_UNAVAILABLE]
            score -= amount
            reductions.append(
                ConfidenceReductionRecord(
                    reason=ConfidenceReduction.LLM_UNAVAILABLE.value,
                    amount=amount,
                    detail=(
                        "Explanation Agent was unavailable; "
                        "LLM assessment could not be produced."
                    ),
                )
            )

        # ---- Clamp and classify --------------------------------------------
        clamped = round(max(0.0, min(1.0, score)), 10)
        level = _classify_confidence(clamped)

        available_count = sum(1 for s in sources if s.available)
        required_count = sum(1 for s in sources if s.required)

        return ConfidenceResult(
            confidence_score=clamped,
            confidence_level=level,
            reductions=reductions,
            sources_available=available_count,
            sources_required=required_count,
        )
