"""
CoordinatorService — Gate 17.

The Sentinel Coordinator is a read-only watsonx Orchestrate agent that
reviews an already-assessed security event and delegates to specialist
collaborators (triage, context, explanation agents) via Orchestrate.

Invocation model (two paths):

  PATH B — watsonx Orchestrate SaaS (primary when provisioned)
    Condition: settings.orchestrate_active == True
               AND settings.orchestrate_coordinator_agent_id is set
    Mechanism: IAM bearer token → /v1/orchestrate/<coordinator-uuid>/chat/completions
    Benefits:  collaborator delegation, Orchestrate traces, agent versioning

  PATH 0 — Deterministic fallback (always available)
    Condition: Path B unavailable or fails
    Mechanism: Summarise persisted assessment fields — no LLM required
    Guarantee: review is always available; event is never lost

Design constraints (master prompt §14, §33, §34, ADR-003, ADR-006):
  - Coordinator NEVER produces risk scores or enforcement decisions.
  - Coordinator NEVER changes event state.
  - Agent output is UNTRUSTED — all fields validated before use.
  - AgentRun row persisted for every call (all paths).
  - Event NEVER lost due to coordinator failure.
  - human_review_required is ALWAYS True in the response.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.agent_run import AgentRun, ToolCall
from app.models.assessment import RiskAssessment
from app.models.event import SecurityEvent
from app.schemas.coordinator import CoordinatorAgentOutput, CoordinatorReview

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Forbidden content that must never appear in the Coordinator summary (§19)
# ---------------------------------------------------------------------------

_FORBIDDEN_WORD_REPLACEMENTS: dict[str, str] = {
    "criminal": "individual",
    "intruder": "unverified individual",
    "suspect": "unverified individual",
    "thief": "individual",
    "attacker": "individual",
    "perpetrator": "individual",
    "felon": "individual",
    "burglar": "individual",
}


class CoordinatorService:
    """
    Invoke the Sentinel Coordinator agent for a read-only review of an
    already-assessed event.

    Parameters
    ----------
    session:
        Active async SQLAlchemy session.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._settings = get_settings()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self, event_id: str) -> CoordinatorReview:
        """
        Run a Coordinator review for *event_id*.

        Returns a :class:`CoordinatorReview` regardless of agent availability.
        Never raises — fallback protects the event in all failure modes.
        """
        # Always create an AgentRun row for observability (ADR-034)
        run_id = str(uuid.uuid4())
        started_at = datetime.now(UTC).isoformat()
        agent_run = AgentRun(
            id=run_id,
            event_id=event_id,
            agent_name="sentinel_coordinator",
            agent_version="v1",
            status="running",
            started_at=started_at,
        )
        self._session.add(agent_run)
        await self._session.flush()

        start_mono = time.monotonic()

        try:
            result = await self._invoke(event_id, run_id)
            source = result.source
            status = "success"
            error_message = None
        except Exception as exc:
            logger.warning(
                "coordinator_service.all_paths_failed",
                event_id=event_id,
                error=str(exc),
            )
            result = await self._deterministic_fallback(event_id, run_id)
            source = "deterministic_fallback"
            status = "fallback"
            error_message = str(exc)[:255]

        duration_ms = (time.monotonic() - start_mono) * 1000

        agent_run.status = status
        agent_run.completed_at = datetime.now(UTC).isoformat()
        agent_run.duration_ms = duration_ms
        agent_run.error_message = error_message
        self._session.add(agent_run)
        await self._session.flush()

        logger.info(
            "coordinator_service.complete",
            event_id=event_id,
            source=source,
            assessment_ready=result.assessment_ready,
            duration_ms=duration_ms,
        )
        return result

    # ------------------------------------------------------------------
    # Invocation paths
    # ------------------------------------------------------------------

    async def _invoke(self, event_id: str, run_id: str) -> CoordinatorReview:
        """Attempt Path B (Orchestrate), fall through to Path 0."""
        settings = self._settings

        if settings.orchestrate_active and settings.orchestrate_coordinator_agent_id:
            try:
                return await self._invoke_orchestrate(event_id, run_id)
            except Exception as exc:
                logger.warning(
                    "coordinator_service.orchestrate_failed",
                    event_id=event_id,
                    error=str(exc),
                )

        return await self._deterministic_fallback(event_id, run_id)

    async def _invoke_orchestrate(self, event_id: str, run_id: str) -> CoordinatorReview:
        """PATH B — call the deployed Coordinator agent via Orchestrate SaaS."""
        from app.services.orchestrate_client import OrchestrateClient

        settings = self._settings
        client = OrchestrateClient(
            base_url=settings.orchestrate_url,
            api_key=settings.effective_orchestrate_api_key,
            timeout=settings.agent_invoke_timeout,
        )

        # Build a compact assessment bundle to supply to the Coordinator
        bundle = await self._load_assessment_bundle(event_id)

        system_prompt = (
            "You are the SentinelIQ Review Coordinator. "
            "Review the supplied assessment bundle for the event. "
            "Preserve all deterministic values exactly. "
            "End your response with a clear statement that human review is required. "
            "Return valid JSON only — no prose, no markdown fences. "
            "human_review_required MUST be true."
        )
        content, tool_calls_telemetry = await client.chat(
            agent_id=settings.orchestrate_coordinator_agent_id,
            system_prompt=system_prompt,
            input_payload=bundle,
        )

        # Persist tool-call telemetry
        for idx, tc in enumerate(tool_calls_telemetry):
            self._session.add(
                ToolCall(
                    id=str(uuid.uuid4()),
                    agent_run_id=run_id,
                    tool_name=tc.get("tool_name", "orchestrate_chat"),
                    status=tc.get("status", "success"),
                    started_at=datetime.now(UTC).isoformat(),
                    duration_ms=tc.get("duration_ms"),
                    sequence=idx,
                )
            )

        return self._parse_and_validate(event_id, content, run_id, source="orchestrate")

    async def _deterministic_fallback(self, event_id: str, run_id: str) -> CoordinatorReview:
        """PATH 0 — build a review from persisted assessment rows, no LLM."""
        bundle = await self._load_assessment_bundle(event_id)
        event = bundle.get("event", {})
        assessment = bundle.get("assessment", {})

        assessment_ready = bool(assessment)
        missing_evidence: list[str] = list(assessment.get("evidence_errors", {}).keys())

        risk_level = assessment.get("risk_level", "unknown")
        confidence_level = assessment.get("confidence_level", "unknown")
        event_type = event.get("event_type", "event")
        location = event.get("location_id", "unknown location")

        # Build a neutral summary from persisted deterministic facts
        if assessment_ready:
            summary = (
                f"Assessment complete for {event_type} at {location}. "
                f"Risk level is {risk_level}, confidence is {confidence_level}. "
                f"Human review is required before any operational action is taken."
            )
        else:
            summary = (
                f"No completed assessment found for {event_type} at {location}. "
                f"An authorised operator must start assessment through the SentinelIQ "
                f"application. Human review will be required."
            )

        summary = summary[:1024]

        return CoordinatorReview(
            event_id=event_id,
            assessment_ready=assessment_ready,
            summary=summary,
            missing_evidence=missing_evidence[:64],
            human_review_required=True,
            source="deterministic_fallback",
            agent_run_id=run_id,
        )

    # ------------------------------------------------------------------
    # Parse and validate agent output
    # ------------------------------------------------------------------

    def _parse_and_validate(
        self,
        event_id: str,
        raw_content: str,
        run_id: str,
        *,
        source: str,
    ) -> CoordinatorReview:
        """
        Validate raw agent text against :class:`CoordinatorAgentOutput`.

        - Strip markdown fences
        - Validate against strict Pydantic schema
        - Override event_id with the known server-side value (injection defence)
        - Enforce human_review_required = True (ADR-006)
        - Replace forbidden words in summary
        """
        # Strip optional markdown fences produced by some models
        text = raw_content.strip()
        if text.startswith("```"):
            text = text.lstrip("`")
            if text.startswith("json"):
                text = text[4:]
            text = text.rstrip("`").strip()

        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"Coordinator returned non-JSON content: {exc}") from exc

        try:
            output = CoordinatorAgentOutput(**data)
        except ValidationError as exc:
            raise ValueError(f"Coordinator output failed schema validation: {exc}") from exc

        # Security: override event_id; enforce human_review_required
        safe_summary = self._sanitise_summary(str(output.summary)[:1024])
        safe_missing = [str(item)[:256] for item in output.missing_evidence[:64]]

        return CoordinatorReview(
            event_id=event_id,  # server-side value — never trust agent
            assessment_ready=output.assessment_ready,
            summary=safe_summary,
            missing_evidence=safe_missing,
            human_review_required=True,  # ADR-006: always true
            source=source,
            agent_run_id=run_id,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _sanitise_summary(text: str) -> str:
        """Replace forbidden words and truncate to 1024 characters."""
        result = text
        for word, replacement in _FORBIDDEN_WORD_REPLACEMENTS.items():
            result = result.replace(word, replacement)
            result = result.replace(word.capitalize(), replacement.capitalize())
        return result[:1024]

    async def _load_assessment_bundle(self, event_id: str) -> dict[str, Any]:
        """Build a compact assessment bundle for the Coordinator agent input."""
        event_result = await self._session.execute(
            select(SecurityEvent).where(SecurityEvent.id == event_id)
        )
        event: SecurityEvent | None = event_result.scalar_one_or_none()
        if event is None:
            return {"event": {}, "assessment": {}}

        assessment_result = await self._session.execute(
            select(RiskAssessment).where(RiskAssessment.event_id == event_id)
        )
        assessment: RiskAssessment | None = assessment_result.scalar_one_or_none()

        def _load_json(raw: str | None, default: Any) -> Any:
            if not raw:
                return default
            try:
                return json.loads(raw)
            except (TypeError, ValueError):
                return default

        event_bundle: dict[str, Any] = {
            "event_id": event.id,
            "event_type": event.event_type,
            "event_timestamp": str(event.event_timestamp) if event.event_timestamp else None,
            "location_id": event.location_id,
            "facility_id": event.facility_id,
            "zone": event.zone,
            "status": event.status,
        }

        if assessment is None:
            return {"event": event_bundle, "assessment": {}}

        assessment_bundle: dict[str, Any] = {
            "risk_score": assessment.risk_score,
            "risk_level": assessment.risk_level,
            "risk_policy_version": assessment.risk_policy_version,
            "confidence_score": assessment.confidence_score,
            "confidence_level": assessment.confidence_level,
            "evidence_errors": _load_json(assessment.evidence_errors_json, {}),
            "triage": _load_json(assessment.triage_result_json, {}),
            "context": _load_json(assessment.context_result_json, {}),
            "explanation": _load_json(assessment.explanation_result_json, {}),
            "assessed_at": assessment.assessed_at,
        }

        return {"event": event_bundle, "assessment": assessment_bundle}
