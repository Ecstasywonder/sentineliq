"""
TriageService — Gate 14.

Invokes the Triage Agent via the watsonx Orchestrate Agent API.

Design:
  - Calls the Orchestrate /v1/agent_runs endpoint with a structured prompt.
  - Validates the JSON response against TriageResult.
  - Persists an AgentRun + ToolCall record for every invocation.
  - Falls back to deterministic triage if Orchestrate is unavailable or
    returns an invalid response (ADR-003 / fail-safe principle).

Constraints (from master prompt):
  - The Triage Agent CANNOT enforce, escalate, or make risk calculations.
  - It ONLY classifies events and identifies required context.
  - Missing evidence is not negative evidence — the agent is not told about
    evidence; it works from event metadata only.
  - If the agent is unavailable the event is NOT lost; deterministic fallback
    produces a usable (conservative) triage result.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

from app.config import get_settings
from app.models.agent_run import AgentRun, ToolCall

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# watsonx.ai endpoint constants
# ---------------------------------------------------------------------------

# The watsonx.ai Chat API is used directly (no Orchestrate SaaS required).
# Verified working: POST /ml/v1/text/chat?version=2024-09-16 with space_id
_CHAT_PATH = "/ml/v1/text/chat"
_CHAT_VERSION = "2024-09-16"
_DEFAULT_MODEL = "ibm/granite-4-h-small"

# Categories / signals / context sources — must stay in sync with agent.yaml
_ALL_CATEGORIES = {
    "after_hours_presence",
    "restricted_area_access",
    "delivery_event",
    "authorized_access",
    "alarm_event",
    "vehicle_event",
    "unclassified",
}
_ALL_SIGNALS = {
    "after_hours",
    "restricted_zone",
    "forced_entry",
    "no_camera_coverage",
    "repeated_event",
    "low_detector_confidence",
    "missing_event_metadata",
}
_ALL_CONTEXT = {
    "access_control",
    "schedule",
    "location_policy",
    "incident_history",
    "work_orders",
    "delivery_context",
    "visitor_context",
    "integration_health",
}

# Always included in required_context for non-trivial events (conservative default)
_BASELINE_CONTEXT = ["access_control", "schedule", "location_policy", "incident_history"]


# ---------------------------------------------------------------------------
# TriageService
# ---------------------------------------------------------------------------


class TriageService:
    """
    Invokes the Triage Agent and returns a validated TriageResult.

    This service is transport-layer agnostic: it uses httpx for the
    Orchestrate call and sqlalchemy AsyncSession for persistence.
    """

    def __init__(self, session: Any) -> None:
        """
        Args:
            session: Active SQLAlchemy AsyncSession (may be None in unit tests
                     that mock the persistence methods).
        """
        self._session = session
        self._settings = get_settings()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(
        self,
        event_id: str,
        event_metadata: dict[str, Any],
        *,
        timeout: float = 30.0,
    ):
        """
        Triage a single security event.

        Args:
            event_id:        SentinelIQ event UUID.
            event_metadata:  Dict of event fields (from SecurityEvent ORM or
                             EventResponse schema).  Must include at minimum:
                             event_type, event_timestamp, location_id.
            timeout:         Orchestrate HTTP timeout in seconds.

        Returns:
            TriageResult — always returned; falls back to deterministic if
            Orchestrate is unavailable or returns invalid output.
        """
        # Import here to avoid circular import at module level
        from app.schemas.triage import TriageResult

        settings = self._settings
        orchestrate_available = bool(
            settings.orchestrate_base_url and settings.orchestrate_api_key
        )

        run_id = str(uuid.uuid4())
        started_at = datetime.now(UTC).isoformat()
        t0 = time.monotonic()

        if not orchestrate_available:
            logger.info(
                "triage_service.orchestrate_not_configured",
                event_id=event_id,
                action="deterministic_fallback",
            )
            result = self._deterministic_triage(event_id, event_metadata)
            result.agent_run_id = run_id
            await self._persist_agent_run(
                run_id=run_id,
                event_id=event_id,
                started_at=started_at,
                status="skipped",
                duration_ms=(time.monotonic() - t0) * 1000,
                agent_name="sentinel_triage_agent",
                tool_calls=[],
            )
            return result

        # --- Attempt Orchestrate invocation -----------------------------------
        try:
            raw_output, tool_call_records = await self._invoke_orchestrate(
                event_id=event_id,
                event_metadata=event_metadata,
                timeout=timeout,
            )
            duration_ms = (time.monotonic() - t0) * 1000
            result = self._parse_and_validate(event_id, raw_output)
            result.agent_run_id = run_id
            await self._persist_agent_run(
                run_id=run_id,
                event_id=event_id,
                started_at=started_at,
                status="success",
                duration_ms=duration_ms,
                agent_name="sentinel_triage_agent",
                tool_calls=tool_call_records,
            )
            logger.info(
                "triage_service.orchestrate_success",
                event_id=event_id,
                category=result.category,
                urgency_signals=result.urgency_signals,
                duration_ms=round(duration_ms, 1),
            )
            return result

        except Exception as exc:  # noqa: BLE001
            duration_ms = (time.monotonic() - t0) * 1000
            logger.warning(
                "triage_service.orchestrate_error",
                event_id=event_id,
                error=str(exc),
                action="deterministic_fallback",
            )
            result = self._deterministic_triage(event_id, event_metadata)
            result.agent_run_id = run_id
            await self._persist_agent_run(
                run_id=run_id,
                event_id=event_id,
                started_at=started_at,
                status="failed",
                duration_ms=duration_ms,
                error_message=str(exc)[:512],
                agent_name="sentinel_triage_agent",
                tool_calls=[],
            )
            return result

    # ------------------------------------------------------------------
    # watsonx.ai Chat API call
    # ------------------------------------------------------------------

    async def _invoke_orchestrate(
        self,
        event_id: str,
        event_metadata: dict[str, Any],
        timeout: float,
    ) -> tuple[str, list[dict[str, Any]]]:
        """
        Call the watsonx.ai Chat API (POST /ml/v1/text/chat).

        Returns:
            (raw_text_output, tool_call_records)

        Authentication: IBM Cloud IAM bearer token obtained from the API key.
        Space: orchestrate_space_id must point to a space with a WML instance.
        Model: ibm/granite-4-h-small (verified available in the Orchestrate
               Developer Edition space).

        The agent instructions are provided as a system message; the event
        metadata JSON is provided as the user message.
        """
        settings = self._settings
        base_url = settings.orchestrate_base_url.rstrip("/")

        # Obtain IAM bearer token from the API key
        iam_token = await self._get_iam_token(settings.orchestrate_api_key, timeout)

        headers = {
            "Authorization": f"Bearer {iam_token}",
            "Content-Type": "application/json",
        }

        # Build the system instructions (mirrors agent.yaml instructions)
        system_prompt = (
            "You are the SentinelIQ Triage Agent.\n"
            "Classify the security event and return ONLY valid JSON with these exact keys:\n"
            "  event_id, category, urgency_signals, required_context, triage_rationale\n"
            "category MUST be one of: after_hours_presence, restricted_area_access, "
            "delivery_event, authorized_access, alarm_event, vehicle_event, unclassified\n"
            "urgency_signals MUST only use: after_hours, restricted_zone, forced_entry, "
            "no_camera_coverage, low_detector_confidence, missing_event_metadata, repeated_event\n"
            "required_context MUST only use: access_control, schedule, location_policy, "
            "incident_history, work_orders, delivery_context, visitor_context, integration_health\n"
            "Return JSON only — no prose, no markdown, no explanation."
        )

        payload: dict[str, Any] = {
            "model_id": _DEFAULT_MODEL,
            "space_id": settings.orchestrate_space_id,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(event_metadata, default=str)},
            ],
            "parameters": {
                "max_new_tokens": 300,
                "decoding_method": "greedy",
            },
        }

        tool_call_records: list[dict[str, Any]] = []
        url = f"{base_url}{_CHAT_PATH}?version={_CHAT_VERSION}"

        async with httpx.AsyncClient(timeout=timeout) as client:
            t_tool = time.monotonic()
            response = await client.post(url, headers=headers, json=payload)
            call_ms = (time.monotonic() - t_tool) * 1000
            response.raise_for_status()

        data = response.json()

        tool_call_records.append({
            "tool_name": "watsonx_chat",
            "status": "success",
            "duration_ms": call_ms,
            "sequence": 0,
        })

        choices = data.get("choices") or []
        if not choices:
            raise ValueError("watsonx.ai response contained no choices.")
        content = (choices[0].get("message") or {}).get("content", "")
        if not content:
            raise ValueError("watsonx.ai response content was empty.")

        return content, tool_call_records

    async def _get_iam_token(self, api_key: str, timeout: float) -> str:
        """Exchange an IBM Cloud API key for a short-lived IAM bearer token."""
        async with httpx.AsyncClient(timeout=min(timeout, 15.0)) as client:
            resp = await client.post(
                "https://iam.cloud.ibm.com/identity/token",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                    "apikey": api_key,
                },
            )
            resp.raise_for_status()
        token_data = resp.json()
        access_token = token_data.get("access_token", "")
        if not access_token:
            raise ValueError("IAM token exchange returned no access_token.")
        return access_token

    # ------------------------------------------------------------------
    # Response validation
    # ------------------------------------------------------------------

    def _parse_and_validate(self, event_id: str, raw_output: str) -> Any:
        """
        Parse the agent's JSON output and validate against TriageResult.

        Raises ValueError if the output cannot be parsed or is invalid.
        """
        from app.schemas.triage import TriageResult

        # Strip markdown fences if the model wrapped the JSON
        text = raw_output.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(
                line for line in lines
                if not line.startswith("```")
            ).strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Triage agent returned non-JSON output: {exc}") from exc

        # Ensure event_id matches
        data["event_id"] = event_id

        # Filter to only allowed values (security: agent output is untrusted)
        raw_category = data.get("category", "unclassified")
        data["category"] = (
            raw_category if raw_category in _ALL_CATEGORIES else "unclassified"
        )
        data["urgency_signals"] = [
            s for s in (data.get("urgency_signals") or []) if s in _ALL_SIGNALS
        ]
        data["required_context"] = list(
            {c for c in (data.get("required_context") or []) if c in _ALL_CONTEXT}
            | set(_BASELINE_CONTEXT)
        )
        # Truncate rationale to prevent injected text reaching the audit trail
        rationale = str(data.get("triage_rationale", ""))[:512]
        data["triage_rationale"] = rationale
        data["source"] = "orchestrate"

        return TriageResult(**data)

    # ------------------------------------------------------------------
    # Deterministic fallback
    # ------------------------------------------------------------------

    def _deterministic_triage(
        self,
        event_id: str,
        event_metadata: dict[str, Any],
    ) -> Any:
        """
        Produce a conservative triage result without calling any LLM.

        This ensures the event is never lost when Orchestrate is unavailable.
        The fallback logic mirrors the rules in agent.yaml instructions so that
        the outcome is predictable and testable.
        """
        from app.schemas.triage import TriageResult

        event_type = str(event_metadata.get("event_type", ""))
        zone = str(event_metadata.get("zone") or "")
        timestamp = str(event_metadata.get("event_timestamp") or "")
        detector_confidence = event_metadata.get("detector_confidence")
        camera_id = event_metadata.get("camera_id")

        signals: list[str] = []
        required_context: list[str] = list(_BASELINE_CONTEXT)

        # After-hours check (hour >= 20 or < 6 UTC)
        try:
            hour = int(timestamp[11:13])
            if hour >= 20 or hour < 6:
                signals.append("after_hours")
        except (ValueError, IndexError):
            signals.append("missing_event_metadata")

        # Restricted zone
        if "restricted" in zone.lower():
            signals.append("restricted_zone")

        # Forced entry / alarm
        if event_type in ("door_forced", "alarm_triggered"):
            signals.append("forced_entry")

        # Low detector confidence
        if detector_confidence is None or (
            isinstance(detector_confidence, float) and detector_confidence < 0.5
        ):
            signals.append("low_detector_confidence")

        # No camera coverage
        if not camera_id:
            signals.append("no_camera_coverage")

        # Determine category
        if event_type in ("door_forced", "alarm_triggered"):
            category = "alarm_event"
        elif event_type == "delivery_detected":
            category = "delivery_event"
            required_context.append("delivery_context")
        elif event_type == "vehicle_detected":
            category = "vehicle_event"
        elif "restricted" in zone.lower() or "after_hours" in signals:
            category = "after_hours_presence"
        elif event_type == "badge_event":
            category = "authorized_access"
        else:
            category = "unclassified"

        # Add work_orders context for non-trivial events
        if any(s in signals for s in ("after_hours", "restricted_zone", "forced_entry")):
            required_context.append("work_orders")

        rationale = (
            f"Deterministic fallback triage: event_type={event_type}, "
            f"zone={zone or 'unset'}, signals={signals}"
        )[:512]

        return TriageResult(
            event_id=event_id,
            category=category,
            urgency_signals=list(dict.fromkeys(signals)),  # deduplicate, preserve order
            required_context=list(dict.fromkeys(required_context)),
            triage_rationale=rationale,
            source="deterministic_fallback",
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _persist_agent_run(
        self,
        *,
        run_id: str,
        event_id: str,
        started_at: str,
        status: str,
        duration_ms: float,
        agent_name: str,
        tool_calls: list[dict[str, Any]],
        error_message: str | None = None,
    ) -> None:
        """Persist an AgentRun + ToolCall rows for observability."""
        if self._session is None:
            return

        completed_at = datetime.now(UTC).isoformat()
        agent_run = AgentRun(
            id=run_id,
            event_id=event_id,
            agent_name=agent_name,
            agent_version="gate-14",
            status=status,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=round(duration_ms, 2),
            error_message=error_message,
        )
        self._session.add(agent_run)

        for seq, tc in enumerate(tool_calls):
            self._session.add(
                ToolCall(
                    id=str(uuid.uuid4()),
                    agent_run_id=run_id,
                    tool_name=tc.get("tool_name", "unknown"),
                    status=tc.get("status", "success"),
                    started_at=started_at,
                    completed_at=completed_at,
                    duration_ms=round(tc.get("duration_ms", 0.0), 2),
                    sequence=seq,
                    error_message=tc.get("error_message"),
                )
            )

        await self._session.flush()
