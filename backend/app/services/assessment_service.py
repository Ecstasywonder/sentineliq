"""
AssessmentService — Gate 8 / Gate 14 / Gate 15 / Master Build Prompt Gate 13.

Orchestrates:
  0. TriageService.run()          — classify event + identify required context (Gate 14)
  1. EvidenceAggregator.gather()  — collect all 7 evidence sources
  1b. ContextService.run()        — interpret evidence, detect conflicts (Gate 15)
  2. _build_signals()             — derive FactorSignals from evidence
  3. RiskEngine.assess()          — deterministic risk score (ADR-003)
  4. ConfidenceEngine.assess()    — independent confidence score (ADR-004)
  4b. ExplanationService.run()    — grounded operator narrative (Master Build Prompt Gate 13)
  5. Persist RiskAssessment + ConfidenceAssessment rows
  6. Denormalise risk/confidence back onto SecurityEvent
  7. Transition event: normalised → assessing → awaiting_review

The event is NEVER lost due to a triage (legacy Gate 14), context (legacy Gate 15),
or explanation (Master Build Prompt Gate 13) failure.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.assessment import ConfidenceAssessment, RiskAssessment
from app.models.audit import AuditEvent
from app.models.event import SecurityEvent
from app.schemas.assessment import AssessmentResponse, ConfidenceReductionDetail, RiskFactorDetail
from app.schemas.context import ContextResultDetail
from app.schemas.explanation import ExplanationResultDetail
from app.schemas.triage import TriageResultDetail
from app.services.confidence_engine import ConfidenceEngine, SourceStatus
from app.services.context_service import ContextService
from app.services.event_lifecycle import validate_transition
from app.services.evidence_aggregator import EvidenceAggregator
from app.services.explanation_service import ExplanationService
from app.services.risk_engine import FactorSignal, RiskEngine
from app.services.triage_service import TriageService

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Source IDs — must match adapter source_id constants
# ---------------------------------------------------------------------------
_REQUIRED_SOURCE_IDS = (
    "mock_access_control",
    "mock_schedule",
    "mock_work_order",
    "mock_delivery",
    "db_security_rules",
    "db_incident_history",
)

_EVIDENCE_ERROR_SOURCE_IDS = {
    "access_events": "mock_access_control",
    "schedule": "mock_schedule",
    "work_orders": "mock_work_order",
    "delivery": "mock_delivery",
    "location_policy": "db_security_rules",
    "incident_history": "db_incident_history",
}


# ---------------------------------------------------------------------------
# Assessment Service
# ---------------------------------------------------------------------------


class AssessmentService:
    """
    Runs the full synchronous assessment pipeline for a single SecurityEvent.

    Parameters
    ----------
    session:
        Active async DB session.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._settings = get_settings()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(
        self,
        event_id: str,
        *,
        unavailable_source_ids: list[str] | None = None,
        policy_version: str | None = None,
    ) -> AssessmentResponse:
        """
        Execute the full assessment pipeline for *event_id*.

        Args:
            event_id:                ID of an existing SecurityEvent.
            unavailable_source_ids:  Additional source IDs the caller knows
                                     are offline (supplements aggregator errors).
            policy_version:          Override the active risk policy version.

        Returns:
            AssessmentResponse ready to serialise to the caller.

        Raises:
            ValueError:  Event not found, or event is in a terminal state.
            InvalidTransitionError:  Event status cannot transition to 'assessing'.
        """
        extra_unavailable = {
            _EVIDENCE_ERROR_SOURCE_IDS.get(source_id, source_id)
            for source_id in (unavailable_source_ids or [])
        }

        # ---- 1. Atomically claim the event ----------------------------------
        # The status update is the per-event compare-and-set.  On PostgreSQL a
        # competing UPDATE waits for this transaction and then re-checks the
        # predicate; SQLite applies the same conditional update after its write
        # lock is released.  Exactly one caller can therefore enter the costly
        # pipeline for a normalised/context-incomplete event.
        event, existing_response = await self._claim_event(event_id)
        if existing_response is not None:
            logger.info(
                "assessment_service.idempotent_replay",
                event_id=event_id,
                event_status=event.status,
            )
            return existing_response

        # ---- 0. Triage (Gate 14) — classify event, identify required context --
        triage_svc = TriageService(self._session)
        triage_result = await triage_svc.run(
            event_id=event_id,
            event_metadata={
                "event_id": event.id,
                "event_type": event.event_type,
                "event_timestamp": event.event_timestamp,
                "location_id": event.location_id,
                "facility_id": event.facility_id,
                "camera_id": event.camera_id,
                "zone": event.zone,
                "detector_confidence": event.detector_confidence,
            },
        )

        # Store agent_run_id on the event for traceability
        if triage_result.agent_run_id:
            event.agent_run_id = triage_result.agent_run_id

        # ---- 3. Gather evidence ---------------------------------------------
        aggregator = EvidenceAggregator(self._session)
        evidence = await aggregator.gather(
            event_id,
            event.location_id,
            facility_id=event.facility_id,
        )

        # ---- 3b. Context Agent — interpret evidence (Gate 15) ---------------
        context_svc = ContextService(self._session)
        context_result = await context_svc.run(
            event_id=event_id,
            event_metadata={
                "event_type": event.event_type,
                "event_timestamp": str(event.event_timestamp),
                "location_id": event.location_id,
                "facility_id": event.facility_id,
                "zone": event.zone,
            },
            required_context=list(triage_result.required_context),
            evidence=evidence,
        )

        # ---- 4. Build risk signals from evidence ----------------------------
        signals = self._build_signals(evidence, event)

        # ---- 5. Run Risk Engine (deterministic, no LLM) ---------------------
        engine = RiskEngine(self._session)
        risk_result = await engine.assess(
            signals,
            policy_version=policy_version or self._settings.active_risk_policy_version,
        )

        # ---- 6. Build confidence source statuses ----------------------------
        normalized_evidence_errors = self._normalize_evidence_errors(evidence.errors)
        sources = self._build_source_statuses(
            evidence,
            extra_unavailable,
            normalized_evidence_errors,
        )
        tool_errors = list(normalized_evidence_errors)

        conf_engine = ConfidenceEngine()
        conf_result = conf_engine.assess(
            sources=sources,
            has_contradictory_evidence=context_result.has_conflicts,
            incomplete_event_metadata=not bool(event.location_id),
            tool_retrieval_errors=tool_errors,
        )

        # ---- 6b. Explanation Agent — grounded operator narrative (Gate 13) --
        explanation_svc = ExplanationService(self._session)
        risk_factors_dicts = [
            {
                "factor_id": f.factor_id,
                "label": f.label,
                "triggered": f.triggered,
                "contribution": f.contribution,
            }
            for f in risk_result.factors
        ]
        explanation_result = await explanation_svc.run(
            event_id=event_id,
            event_metadata={
                "event_type": event.event_type,
                "event_timestamp": str(event.event_timestamp),
                "location_id": event.location_id,
                "facility_id": event.facility_id,
                "zone": event.zone,
            },
            triage_result=triage_result,
            context_result=context_result,
            risk_score=risk_result.risk_score,
            risk_level=risk_result.risk_level,
            risk_factors=risk_factors_dicts,
            confidence_score=conf_result.confidence_score,
            confidence_level=conf_result.confidence_level,
            evidence_errors=normalized_evidence_errors,
            evidence=evidence,
        )

        # ---- 7. Persist assessment rows -------------------------------------
        assessed_at = datetime.now(UTC).isoformat()
        await self._persist_assessments(
            event_id,
            risk_result,
            conf_result,
            triage_result,
            context_result,
            explanation_result,
            normalized_evidence_errors,
            assessed_at,
        )

        # ---- 8. Denormalise onto event + transition to awaiting_review ------
        event.risk_score = risk_result.risk_score
        event.risk_level = risk_result.risk_level
        event.confidence_score = conf_result.confidence_score
        event.confidence_level = conf_result.confidence_level
        validate_transition(event.status, "awaiting_review")
        event.status = "awaiting_review"
        self._session.add(event)

        # Write immutable audit trail entry for the assessment
        self._session.add(AuditEvent(
            id=str(uuid.uuid4()),
            event_id=event_id,
            action="risk_assessed",
            actor="system:assessment_service",
            occurred_at=assessed_at,
            details_json=json.dumps({
                "risk_score": risk_result.risk_score,
                "risk_level": risk_result.risk_level,
                "confidence_score": conf_result.confidence_score,
                "confidence_level": conf_result.confidence_level,
                "sources_available": conf_result.sources_available,
                "evidence_errors": normalized_evidence_errors,
                "triage_agent_run_id": triage_result.agent_run_id,
                "context_agent_run_id": context_result.agent_run_id,
                "explanation_agent_run_id": explanation_result.agent_run_id,
                "triage": triage_result.model_dump(mode="json"),
                "context": context_result.model_dump(mode="json"),
                "explanation": explanation_result.model_dump(mode="json"),
                "workflow_state": {
                    "before": "assessing",
                    "after": "awaiting_review",
                },
            }),
        ))

        await self._session.flush()

        logger.info(
            "assessment_service.complete",
            event_id=event_id,
            risk_score=risk_result.risk_score,
            risk_level=risk_result.risk_level,
            confidence_score=conf_result.confidence_score,
            confidence_level=conf_result.confidence_level,
            evidence_errors=list(normalized_evidence_errors),
        )

        triage_detail = TriageResultDetail(
            category=triage_result.category,
            urgency_signals=triage_result.urgency_signals,
            required_context=triage_result.required_context,
            triage_rationale=triage_result.triage_rationale,
            source=triage_result.source,
            agent_run_id=triage_result.agent_run_id,
        )

        context_detail = ContextResultDetail(
            source_statuses=context_result.source_statuses,
            conflicts=context_result.conflicts,
            missing_sources=context_result.missing_sources,
            context_summary=context_result.context_summary,
            has_conflicts=context_result.has_conflicts,
            has_missing_sources=context_result.has_missing_sources,
            source=context_result.source,
            agent_run_id=context_result.agent_run_id,
        )

        explanation_detail = ExplanationResultDetail(
            summary=explanation_result.summary,
            risk_level=explanation_result.risk_level,
            risk_score=explanation_result.risk_score,
            confidence_score=explanation_result.confidence_score,
            why=explanation_result.why,
            missing_evidence=explanation_result.missing_evidence,
            limitations=explanation_result.limitations,
            recommended_action=explanation_result.recommended_action,
            has_missing_evidence=explanation_result.has_missing_evidence,
            has_limitations=explanation_result.has_limitations,
            source=explanation_result.source,
            agent_run_id=explanation_result.agent_run_id,
        )

        return AssessmentResponse(
            event_id=event_id,
            event_status=event.status,
            triage=triage_detail,
            context=context_detail,
            explanation=explanation_detail,
            risk_score=risk_result.risk_score,
            risk_level=risk_result.risk_level,
            risk_policy_version=risk_result.policy_version,
            risk_factors=[
                RiskFactorDetail(
                    factor_id=f.factor_id,
                    label=f.label,
                    weight=f.weight,
                    direction=f.direction,
                    triggered=f.triggered,
                    contribution=f.contribution,
                )
                for f in risk_result.factors
            ],
            confidence_score=conf_result.confidence_score,
            confidence_level=conf_result.confidence_level,
            confidence_reductions=[
                ConfidenceReductionDetail(
                    reason=r.reason,
                    amount=r.amount,
                    source_id=r.source_id,
                    detail=r.detail,
                )
                for r in conf_result.reductions
            ],
            sources_available=conf_result.sources_available,
            sources_required=conf_result.sources_required,
            evidence_errors=normalized_evidence_errors,
            assessed_at=assessed_at,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _load_event(self, event_id: str) -> SecurityEvent:
        stmt = (
            select(SecurityEvent)
            .where(SecurityEvent.id == event_id)
            .execution_options(populate_existing=True)
        )
        result = await self._session.execute(stmt)
        event: SecurityEvent | None = result.scalar_one_or_none()
        if event is None:
            raise ValueError(f"Event '{event_id}' not found.")
        return event

    async def _claim_event(
        self,
        event_id: str,
    ) -> tuple[SecurityEvent, AssessmentResponse | None]:
        """Claim one assessment run or replay its already-persisted result.

        ``normalised`` is the normal entry state. ``context_incomplete`` is
        also claimable so an operator can retry a run after missing evidence is
        restored. An existing assessment in any later lifecycle state is
        returned without resetting that state, which keeps human decisions
        non-bypassable and makes duplicate POSTs idempotent.
        """
        claim = (
            update(SecurityEvent)
            .where(
                SecurityEvent.id == event_id,
                SecurityEvent.status.in_(("normalised", "context_incomplete")),
            )
            .values(status="assessing")
            .execution_options(synchronize_session=False)
        )
        result = await self._session.execute(claim)
        if result.rowcount == 1:
            event = await self._load_event(event_id)
            return event, None

        event = await self._load_event(event_id)
        persisted = await self._response_from_persisted(event)
        if persisted is not None:
            return event, persisted

        if event.status == "assessing":
            raise ValueError(
                f"Event '{event_id}' is already being assessed by another request."
            )

        # Preserve the lifecycle service's precise error for terminal or
        # otherwise invalid states.
        validate_transition(event.status, "assessing")
        raise ValueError(
            f"Event '{event_id}' could not be claimed for assessment from "
            f"status '{event.status}'."
        )

    async def _response_from_persisted(
        self,
        event: SecurityEvent,
    ) -> AssessmentResponse | None:
        """Reconstruct an idempotent response without re-running any agents."""
        risk_result = await self._session.execute(
            select(RiskAssessment).where(RiskAssessment.event_id == event.id)
        )
        risk_row = risk_result.scalar_one_or_none()
        if risk_row is None:
            return None

        conf_result = await self._session.execute(
            select(ConfidenceAssessment).where(
                ConfidenceAssessment.event_id == event.id
            )
        )
        conf_row = conf_result.scalar_one_or_none()

        def _json_value(raw: str | None, default):
            if not raw:
                return default
            try:
                return json.loads(raw)
            except (TypeError, ValueError):
                return default

        def _snapshot(raw: str | None, schema):
            value = _json_value(raw, None)
            if not isinstance(value, dict):
                return None
            try:
                return schema(**value)
            except (TypeError, ValueError):
                return None

        factors: list[RiskFactorDetail] = []
        for value in _json_value(risk_row.risk_factors_json, []):
            try:
                factors.append(RiskFactorDetail(**value))
            except (TypeError, ValueError):
                logger.warning(
                    "assessment_service.invalid_persisted_factor",
                    event_id=event.id,
                )

        reductions: list[ConfidenceReductionDetail] = []
        reductions_raw = (
            conf_row.reductions_json
            if conf_row is not None
            else risk_row.confidence_reductions_json
        )
        for value in _json_value(reductions_raw, []):
            try:
                reductions.append(ConfidenceReductionDetail(**value))
            except (TypeError, ValueError):
                logger.warning(
                    "assessment_service.invalid_persisted_reduction",
                    event_id=event.id,
                )

        triage = _snapshot(risk_row.triage_result_json, TriageResultDetail)
        context = _snapshot(risk_row.context_result_json, ContextResultDetail)
        explanation = _snapshot(
            risk_row.explanation_result_json,
            ExplanationResultDetail,
        )
        evidence_errors = _json_value(risk_row.evidence_errors_json, {})
        if not isinstance(evidence_errors, dict):
            evidence_errors = {}

        confidence_score = (
            conf_row.confidence_score
            if conf_row is not None
            else risk_row.confidence_score or 0.0
        )
        confidence_level = (
            conf_row.confidence_level
            if conf_row is not None
            else risk_row.confidence_level or "low"
        )

        return AssessmentResponse(
            event_id=event.id,
            event_status=event.status,
            triage=triage,
            context=context,
            explanation=explanation,
            risk_score=risk_row.risk_score,
            risk_level=risk_row.risk_level,
            risk_policy_version=risk_row.risk_policy_version,
            risk_factors=factors,
            confidence_score=confidence_score,
            confidence_level=confidence_level,
            confidence_reductions=reductions,
            sources_available=conf_row.sources_available if conf_row else 0,
            sources_required=conf_row.sources_required if conf_row else 0,
            evidence_errors=evidence_errors,
            assessed_at=risk_row.assessed_at,
        )

    def _build_signals(self, evidence, event: SecurityEvent) -> list[FactorSignal]:
        """
        Derive FactorSignal list from gathered evidence.

        This is the deterministic signal extraction layer.  Each signal maps
        to a ``factor_id`` in the active RiskPolicy.  Unknown factor IDs are
        silently ignored by the RiskEngine (ADR-003).

        Signals produced here (v1.0 policy factors):
          after_hours_access   — access event outside business hours (naive: hour >= 20 or < 6)
          unverified_person    — access_granted=False in any access event
          no_work_order        — no active work order for this location
          no_scheduled_entry   — no schedule entry covering this location
          known_incident_area  — location has prior incidents in history
          critical_zone        — security rule marks zone as restricted
        """
        signals: list[FactorSignal] = []

        # --- after_hours_access -----------------------------------------------
        after_hours = False
        if evidence.access_events and evidence.access_events.records:
            for rec in evidence.access_events.records:
                try:
                    hour = int(rec.occurred_at[11:13])  # "2026-11-03T22:00:00Z" → 22
                    if hour >= 20 or hour < 6:
                        after_hours = True
                        break
                except (ValueError, IndexError):
                    pass
        signals.append(
            FactorSignal(
                factor_id="after_hours_access",
                triggered=after_hours,
                source="access_events",
            )
        )

        # --- unverified_person -----------------------------------------------
        unverified = False
        if evidence.access_events and evidence.access_events.records:
            unverified = any(
                not rec.access_granted for rec in evidence.access_events.records
            )
        signals.append(
            FactorSignal(
                factor_id="unverified_person",
                triggered=unverified,
                source="access_events",
            )
        )

        # --- no_work_order ---------------------------------------------------
        has_work_order = bool(
            evidence.work_orders
            and evidence.work_orders.meta.record_count > 0
        )
        signals.append(
            FactorSignal(
                factor_id="no_work_order",
                triggered=not has_work_order,
                source="work_orders",
            )
        )

        # --- no_scheduled_entry ---------------------------------------------
        has_schedule = bool(
            evidence.schedule
            and evidence.schedule.meta.record_count > 0
        )
        signals.append(
            FactorSignal(
                factor_id="no_scheduled_entry",
                triggered=not has_schedule,
                source="schedule",
            )
        )

        # --- known_incident_area --------------------------------------------
        has_incidents = bool(
            evidence.incident_history
            and evidence.incident_history.meta.record_count > 0
        )
        signals.append(
            FactorSignal(
                factor_id="known_incident_area",
                triggered=has_incidents,
                source="incident_history",
            )
        )

        # --- critical_zone --------------------------------------------------
        is_restricted = False
        if evidence.location_policy and evidence.location_policy.records:
            is_restricted = any(
                r.rule_type in ("after_hours_restriction", "access_restriction", "restricted_zone")
                for r in evidence.location_policy.records
                if r.is_active
            )
        signals.append(
            FactorSignal(
                factor_id="critical_zone",
                triggered=is_restricted,
                source="location_policy",
            )
        )

        return signals

    def _build_source_statuses(
        self,
        evidence,
        extra_unavailable: set[str],
        normalized_errors: dict[str, str] | None = None,
    ) -> list[SourceStatus]:
        """Map aggregated evidence sections to SourceStatus for ConfidenceEngine."""
        section_map = {
            "mock_access_control": evidence.access_events,
            "mock_schedule": evidence.schedule,
            "mock_work_order": evidence.work_orders,
            "mock_delivery": evidence.delivery,
            "db_security_rules": evidence.location_policy,
            "db_incident_history": evidence.incident_history,
        }
        statuses: list[SourceStatus] = []
        for source_id in _REQUIRED_SOURCE_IDS:
            section = section_map.get(source_id)
            available = (
                section is not None
                and source_id not in (normalized_errors or {})
                and source_id not in extra_unavailable
            )
            statuses.append(
                SourceStatus(
                    source_id=source_id,
                    available=available,
                    stale=False,
                    required=True,
                )
            )
        return statuses

    def _normalize_evidence_errors(self, errors: dict[str, str]) -> dict[str, str]:
        """Translate aggregator section keys to canonical adapter/source IDs."""
        return {
            _EVIDENCE_ERROR_SOURCE_IDS.get(section, section): message
            for section, message in errors.items()
        }

    async def _persist_assessments(
        self,
        event_id: str,
        risk_result,
        conf_result,
        triage_result,
        context_result,
        explanation_result,
        evidence_errors: dict[str, str],
        assessed_at: str,
    ) -> None:
        """
        Upsert RiskAssessment and ConfidenceAssessment rows.

        If an assessment already exists for this event (re-assessment),
        delete the old row first so the unique constraint on event_id is
        not violated.
        """
        from sqlalchemy import delete

        # Delete existing assessments (idempotent re-assessment support)
        await self._session.execute(
            delete(RiskAssessment).where(RiskAssessment.event_id == event_id)
        )
        await self._session.execute(
            delete(ConfidenceAssessment).where(ConfidenceAssessment.event_id == event_id)
        )

        risk_row = RiskAssessment(
            id=str(uuid.uuid4()),
            event_id=event_id,
            risk_policy_version=risk_result.policy_version,
            risk_score=risk_result.risk_score,
            risk_level=risk_result.risk_level,
            risk_factors_json=risk_result.factors_json,
            confidence_score=conf_result.confidence_score,
            confidence_level=conf_result.confidence_level,
            confidence_reductions_json=conf_result.reductions_json,
            triage_result_json=json.dumps(triage_result.model_dump(mode="json"), default=str),
            context_result_json=json.dumps(context_result.model_dump(mode="json"), default=str),
            explanation_result_json=json.dumps(
                explanation_result.model_dump(mode="json"), default=str
            ),
            evidence_errors_json=json.dumps(evidence_errors),
            workflow_state_json=json.dumps({
                "before": "assessing",
                "after": "awaiting_review",
            }),
            assessed_at=assessed_at,
            agent_run_id=explanation_result.agent_run_id,
        )
        conf_row = ConfidenceAssessment(
            id=str(uuid.uuid4()),
            event_id=event_id,
            confidence_score=conf_result.confidence_score,
            confidence_level=conf_result.confidence_level,
            reductions_json=conf_result.reductions_json,
            sources_available=conf_result.sources_available,
            sources_required=conf_result.sources_required,
            assessed_at=assessed_at,
        )
        self._session.add(risk_row)
        self._session.add(conf_row)
        await self._session.flush()
