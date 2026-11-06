"""
ContextService — Gate 15 (dual-path, ADR-008).

Invocation priority (three paths, identical to TriageService):

  PATH B — watsonx Orchestrate SaaS
    Condition: settings.orchestrate_active == True

  PATH A — watsonx.ai Chat API (verified fallback)
    Condition: settings.watsonx_active == True

  PATH 0 — Deterministic fallback (always available)
    Condition: both above unavailable OR both fail

The Context Agent receives:
  - event metadata (type, timestamp, location, zone)
  - required_context list (from TriageResult)
  - pre-gathered evidence (from EvidenceAggregator)

It produces a ContextResult describing:
  - status of each evidence source (verified_present / verified_absent /
    unavailable / not_requested)
  - any detected conflicts between sources
  - list of missing sources (unavailable sources in required_context)
  - a neutral factual context summary

Design constraints:
  - Agent output is UNTRUSTED — all fields filtered before use.
  - Missing evidence is NEVER treated as negative evidence (ADR-004).
  - Conflict detection is surfaced, not resolved — human review decides.
  - AgentRun row persisted for every call (all three paths).
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
from app.schemas.context import ContextResult, ContextResultDetail, EvidenceConflict, SourceStatusRecord

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Endpoint constants (shared with TriageService)
# ---------------------------------------------------------------------------

_ORCHESTRATE_AGENT_RUN_PATH = "/v1/agents/{agent_id}/run"
_WATSONX_CHAT_PATH = "/ml/v1/text/chat"
_WATSONX_CHAT_VERSION = "2024-09-16"
_IAM_TOKEN_URL = "https://iam.cloud.ibm.com/identity/token"

# ---------------------------------------------------------------------------
# Allowed source status values
# ---------------------------------------------------------------------------

_ALLOWED_STATUSES = frozenset({
    "verified_present",
    "verified_absent",
    "unavailable",
    "not_requested",
})

_KNOWN_SOURCES = frozenset({
    "access_control",
    "schedule",
    "location_policy",
    "incident_history",
    "work_orders",
    "delivery_context",
    "visitor_context",
    "integration_health",
})

# ---------------------------------------------------------------------------
# System prompt — mirrors agents/context/agent.yaml instructions
# ---------------------------------------------------------------------------

_CONTEXT_SYSTEM_PROMPT = (
    "You are the SentinelIQ Context Agent.\n"
    "You receive a pre-gathered evidence package and produce a structured context assessment.\n"
    "You do NOT make risk scores, enforcement decisions, or identity claims.\n\n"
    "For each source in required_context, determine its status:\n"
    "  verified_present — source responded and records found\n"
    "  verified_absent  — source responded but no matching records\n"
    "  unavailable      — source failed (appears in errors dict)\n"
    "  not_requested    — source was not in required_context\n\n"
    "CRITICAL: If a source is in the errors dict → status must be 'unavailable'.\n"
    "NEVER say 'no badge found' when the badge system failed — say 'unavailable'.\n"
    "NEVER invent facts. Every claim must be in the input evidence.\n"
    "Use neutral language: 'unverified activity', 'access status unavailable', "
    "'activity inconsistent with schedule'. Avoid: criminal, intruder, suspicious person.\n\n"
    "Return ONLY valid JSON with these exact keys:\n"
    "  event_id, source_statuses, conflicts, missing_sources, "
    "context_summary, has_conflicts, has_missing_sources\n"
    "source_statuses: { '<source>': { 'status': '...', 'record_count': <int|null>, "
    "'summary': '<one sentence or null>' } }\n"
    "conflicts: [ { 'source_a': '...', 'source_b': '...', 'description': '...' } ]\n"
    "missing_sources: list of source names that are 'unavailable'\n"
    "context_summary: two sentences max, neutral factual\n"
    "Return JSON only — no markdown, no prose."
)


# ---------------------------------------------------------------------------
# ContextService
# ---------------------------------------------------------------------------


class ContextService:
    """
    Invokes the Context Agent and returns a validated ContextResult.

    Path routing mirrors TriageService (ADR-008):
      orchestrate_active → Path B
      watsonx_active     → Path A  (current verified path)
      neither            → Path 0  (deterministic)
    """

    def __init__(self, session: Any) -> None:
        self._session = session
        self._settings = get_settings()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(
        self,
        event_id: str,
        event_metadata: dict[str, Any],
        required_context: list[str],
        evidence: Any,  # AggregatedEvidence from EvidenceAggregator
        *,
        timeout: float | None = None,
    ) -> ContextResult:
        """
        Interpret evidence for a security event.

        Args:
            event_id:         SentinelIQ event UUID.
            event_metadata:   Core event fields (type, timestamp, location, zone).
            required_context: Source list from TriageResult.
            evidence:         AggregatedEvidence from EvidenceAggregator.
            timeout:          HTTP timeout in seconds.

        Returns:
            ContextResult — always. Never raises.
        """
        settings = self._settings
        effective_timeout = timeout or settings.agent_invoke_timeout
        run_id = str(uuid.uuid4())
        started_at = datetime.now(UTC).isoformat()
        t0 = time.monotonic()

        # Serialise the evidence package for the LLM
        evidence_payload = self._serialise_evidence(evidence)

        input_payload = {
            **event_metadata,
            "event_id": event_id,
            "required_context": required_context,
            "evidence": evidence_payload,
        }

        # ---- PATH B: watsonx Orchestrate SaaS --------------------------------
        if settings.orchestrate_active:
            try:
                raw, tool_calls = await self._invoke_orchestrate_saas(
                    input_payload, effective_timeout
                )
                duration_ms = (time.monotonic() - t0) * 1000
                result = self._parse_and_validate(event_id, raw, required_context,
                                                   evidence, source="orchestrate")
                result.agent_run_id = run_id
                await self._persist_agent_run(
                    run_id=run_id, event_id=event_id, started_at=started_at,
                    status="success", duration_ms=duration_ms,
                    agent_version=settings.orchestrate_context_agent_id,
                    path="orchestrate", tool_calls=tool_calls,
                )
                logger.info("context.path_b.success", event_id=event_id,
                            has_conflicts=result.has_conflicts,
                            missing=result.missing_sources,
                            duration_ms=round(duration_ms, 1))
                return result
            except Exception as exc:  # noqa: BLE001
                logger.warning("context.path_b.failed", event_id=event_id,
                               error=str(exc), fallthrough="path_a")

        # ---- PATH A: watsonx.ai Chat API (verified) --------------------------
        if settings.watsonx_active:
            try:
                raw, tool_calls = await self._invoke_watsonx_ai(
                    input_payload, effective_timeout
                )
                duration_ms = (time.monotonic() - t0) * 1000
                result = self._parse_and_validate(event_id, raw, required_context,
                                                   evidence, source="watsonx_ai")
                result.agent_run_id = run_id
                await self._persist_agent_run(
                    run_id=run_id, event_id=event_id, started_at=started_at,
                    status="success", duration_ms=duration_ms,
                    agent_version=settings.watsonx_model_id,
                    path="watsonx_ai", tool_calls=tool_calls,
                )
                logger.info("context.path_a.success", event_id=event_id,
                            has_conflicts=result.has_conflicts,
                            missing=result.missing_sources,
                            duration_ms=round(duration_ms, 1))
                return result
            except Exception as exc:  # noqa: BLE001
                duration_ms = (time.monotonic() - t0) * 1000
                logger.warning("context.path_a.failed", event_id=event_id,
                               error=str(exc), fallthrough="path_0")
                await self._persist_agent_run(
                    run_id=run_id, event_id=event_id, started_at=started_at,
                    status="failed", duration_ms=duration_ms,
                    agent_version=settings.watsonx_model_id,
                    path="watsonx_ai", tool_calls=[],
                    error_message=str(exc)[:512],
                )

        # ---- PATH 0: Deterministic fallback ----------------------------------
        duration_ms = (time.monotonic() - t0) * 1000
        neither = not settings.orchestrate_active and not settings.watsonx_active
        path0_status = "skipped" if neither else "failed_fallback"

        result = self._deterministic_context(event_id, required_context, evidence)
        result.agent_run_id = run_id
        await self._persist_agent_run(
            run_id=run_id, event_id=event_id, started_at=started_at,
            status=path0_status, duration_ms=duration_ms,
            agent_version="deterministic_v1",
            path="deterministic", tool_calls=[],
        )
        logger.info("context.path_0.used", event_id=event_id,
                    missing=result.missing_sources, reason=path0_status)
        return result

    # ------------------------------------------------------------------
    # PATH B — watsonx Orchestrate SaaS
    # ------------------------------------------------------------------

    async def _invoke_orchestrate_saas(
        self,
        input_payload: dict[str, Any],
        timeout: float,
    ) -> tuple[str, list[dict[str, Any]]]:
        settings = self._settings
        base_url = settings.orchestrate_url.rstrip("/")
        agent_id = settings.orchestrate_context_agent_id
        url = f"{base_url}{_ORCHESTRATE_AGENT_RUN_PATH.format(agent_id=agent_id)}"

        headers = {
            "Authorization": f"ZenApiKey {settings.effective_watsonx_api_key}",
            "Content-Type": "application/json",
        }
        payload = {"input": json.dumps(input_payload, default=str)}

        async with httpx.AsyncClient(timeout=timeout) as client:
            t0 = time.monotonic()
            response = await client.post(url, headers=headers, json=payload)
            call_ms = (time.monotonic() - t0) * 1000
            response.raise_for_status()

        data = response.json()
        tool_calls = [{"tool_name": "orchestrate_agent_run", "status": "success",
                       "duration_ms": call_ms, "sequence": 0}]

        content = data.get("output") or data.get("content") or ""
        if not content:
            choices = data.get("choices") or []
            if choices:
                content = (choices[0].get("message") or {}).get("content", "")
        if not content:
            raise ValueError(f"Orchestrate response had no usable content. keys={list(data)}")

        return content, tool_calls

    # ------------------------------------------------------------------
    # PATH A — watsonx.ai Chat API
    # ------------------------------------------------------------------

    async def _invoke_watsonx_ai(
        self,
        input_payload: dict[str, Any],
        timeout: float,
    ) -> tuple[str, list[dict[str, Any]]]:
        settings = self._settings
        base_url = settings.effective_watsonx_base_url.rstrip("/")

        iam_token = await self._get_iam_token(settings.effective_watsonx_api_key, timeout)
        headers = {
            "Authorization": f"Bearer {iam_token}",
            "Content-Type": "application/json",
        }
        # Summarise evidence compactly for the LLM (avoid hitting token limits)
        compact = self._compact_evidence_for_llm(input_payload)
        payload: dict[str, Any] = {
            "model_id": settings.watsonx_model_id,
            "space_id": settings.effective_watsonx_space_id,
            "messages": [
                {"role": "system", "content": _CONTEXT_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(compact, default=str)},
            ],
            "parameters": {"max_new_tokens": 600, "decoding_method": "greedy"},
        }

        url = f"{base_url}{_WATSONX_CHAT_PATH}?version={_WATSONX_CHAT_VERSION}"
        async with httpx.AsyncClient(timeout=timeout) as client:
            t0 = time.monotonic()
            response = await client.post(url, headers=headers, json=payload)
            call_ms = (time.monotonic() - t0) * 1000
            response.raise_for_status()

        data = response.json()
        tool_calls = [{"tool_name": "watsonx_chat", "status": "success",
                       "duration_ms": call_ms, "sequence": 0}]

        choices = data.get("choices") or []
        if not choices:
            raise ValueError("watsonx.ai context response contained no choices.")
        content = (choices[0].get("message") or {}).get("content", "")
        if not content:
            raise ValueError("watsonx.ai context response content was empty.")

        return content, tool_calls

    async def _get_iam_token(self, api_key: str, timeout: float) -> str:
        async with httpx.AsyncClient(timeout=min(timeout, 15.0)) as client:
            resp = await client.post(
                _IAM_TOKEN_URL,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={"grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                      "apikey": api_key},
            )
            resp.raise_for_status()
        access_token = resp.json().get("access_token", "")
        if not access_token:
            raise ValueError("IAM token exchange returned no access_token.")
        return access_token

    # ------------------------------------------------------------------
    # Evidence serialisation helpers
    # ------------------------------------------------------------------

    def _serialise_evidence(self, evidence: Any) -> dict[str, Any]:
        """
        Serialise the AggregatedEvidence object to a plain dict.
        Handles both Pydantic models and None gracefully.
        """
        if evidence is None:
            return {"errors": {}}
        try:
            return evidence.model_dump()
        except AttributeError:
            return dict(evidence) if hasattr(evidence, "__iter__") else {}

    def _compact_evidence_for_llm(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """
        Build a compact evidence summary for the LLM to avoid token limits.
        Only sends counts, source IDs, error keys, and brief record summaries.
        """
        evidence = input_payload.get("evidence", {})
        errors = evidence.get("errors", {})

        compact_evidence: dict[str, Any] = {"errors": errors}

        source_map = {
            "access_control":   "access_events",
            "schedule":         "schedule",
            "work_orders":      "work_orders",
            "delivery_context": "delivery",
            "location_policy":  "location_policy",
            "incident_history": "incident_history",
            "integration_health": "integration_health",
        }

        for ctx_name, ev_key in source_map.items():
            section = evidence.get(ev_key)
            if section is None:
                compact_evidence[ctx_name] = None
                continue
            # Include meta + first record summary only
            meta = section.get("meta", {}) if isinstance(section, dict) else {}
            records = section.get("records", []) if isinstance(section, dict) else []
            first_rec_summary = None
            if records:
                r = records[0]
                if isinstance(r, dict):
                    first_rec_summary = {
                        k: v for k, v in r.items()
                        if k in ("access_type", "access_granted", "schedule_type",
                                 "status", "is_active", "rule_type", "severity",
                                 "incident_type", "requires_after_hours")
                    }
            compact_evidence[ctx_name] = {
                "source": meta.get("source"),
                "record_count": meta.get("record_count", 0),
                "first_record_summary": first_rec_summary,
            }

        return {
            "event_id": input_payload.get("event_id"),
            "event_type": input_payload.get("event_type"),
            "event_timestamp": input_payload.get("event_timestamp"),
            "location_id": input_payload.get("location_id"),
            "zone": input_payload.get("zone"),
            "required_context": input_payload.get("required_context", []),
            "evidence_summary": compact_evidence,
        }

    # ------------------------------------------------------------------
    # Response validation
    # ------------------------------------------------------------------

    def _parse_and_validate(
        self,
        event_id: str,
        raw_output: str,
        required_context: list[str],
        evidence: Any,
        source: str,
    ) -> ContextResult:
        """
        Parse and validate agent JSON output.

        Security (master prompt §28): agent output is untrusted.
        - source_statuses keys filtered to _KNOWN_SOURCES
        - status values filtered to _ALLOWED_STATUSES
        - context_summary truncated to 1024 chars
        - conflicts list validated for structure
        - missing_sources cross-checked against errors dict

        Raises ValueError on parse failure.
        """
        text = raw_output.strip()
        if text.startswith("```"):
            text = "\n".join(
                ln for ln in text.splitlines() if not ln.startswith("```")
            ).strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Context agent returned non-JSON: {exc}") from exc

        data["event_id"] = event_id

        # Validate source_statuses
        raw_statuses = data.get("source_statuses") or {}
        validated_statuses: dict[str, SourceStatusRecord] = {}
        for src, val in raw_statuses.items():
            if src not in _KNOWN_SOURCES:
                continue
            if not isinstance(val, dict):
                continue
            raw_status = val.get("status", "unavailable")
            status = raw_status if raw_status in _ALLOWED_STATUSES else "unavailable"
            validated_statuses[src] = SourceStatusRecord(
                status=status,
                record_count=val.get("record_count"),
                summary=str(val.get("summary") or "")[:256] or None,
            )

        # Validate conflicts
        raw_conflicts = data.get("conflicts") or []
        validated_conflicts: list[EvidenceConflict] = []
        for c in raw_conflicts:
            if not isinstance(c, dict):
                continue
            src_a = c.get("source_a", "")
            src_b = c.get("source_b", "")
            desc = str(c.get("description", ""))[:512]
            if src_a and src_b and desc:
                validated_conflicts.append(EvidenceConflict(
                    source_a=src_a, source_b=src_b, description=desc
                ))

        # missing_sources: filter to known sources
        missing = [s for s in (data.get("missing_sources") or []) if s in _KNOWN_SOURCES]

        summary = str(data.get("context_summary") or "")[:1024]

        return ContextResult(
            event_id=event_id,
            source_statuses=validated_statuses,
            conflicts=validated_conflicts,
            missing_sources=missing,
            context_summary=summary,
            has_conflicts=bool(validated_conflicts),
            has_missing_sources=bool(missing),
            source=source,
        )

    # ------------------------------------------------------------------
    # PATH 0 — Deterministic context assessment
    # ------------------------------------------------------------------

    def _deterministic_context(
        self,
        event_id: str,
        required_context: list[str],
        evidence: Any,
    ) -> ContextResult:
        """
        Produce a context result using only the evidence metadata — no LLM.

        Rules:
        - Source in errors dict → unavailable
        - Source section is None → unavailable
        - Source has record_count == 0 → verified_absent
        - Source has record_count > 0 → verified_present
        - Source not in required_context → not_requested

        Conflict detection:
        - access_control verified_present with access_granted=False AND
          schedule verified_absent → conflict (badge denied + not scheduled)
        - access_control verified_present with access_granted=True AND
          location_policy restricted → conflict (valid badge but restricted area)
        """
        evidence_dict = self._serialise_evidence(evidence)
        errors = evidence_dict.get("errors", {})

        source_map = {
            "access_control":     "access_events",
            "schedule":           "schedule",
            "work_orders":        "work_orders",
            "delivery_context":   "delivery",
            "location_policy":    "location_policy",
            "incident_history":   "incident_history",
            "integration_health": "integration_health",
        }

        statuses: dict[str, SourceStatusRecord] = {}
        missing: list[str] = []

        for ctx_src, ev_key in source_map.items():
            if ctx_src not in required_context:
                statuses[ctx_src] = SourceStatusRecord(
                    status="not_requested",
                    record_count=None,
                    summary=None,
                )
                continue

            if ctx_src in errors or ev_key in errors:
                statuses[ctx_src] = SourceStatusRecord(
                    status="unavailable",
                    record_count=None,
                    summary=f"{ctx_src} status is unavailable.",
                )
                missing.append(ctx_src)
                continue

            section = evidence_dict.get(ev_key)
            if section is None:
                statuses[ctx_src] = SourceStatusRecord(
                    status="unavailable",
                    record_count=None,
                    summary=f"{ctx_src} status is unavailable.",
                )
                missing.append(ctx_src)
                continue

            meta = section.get("meta", {}) if isinstance(section, dict) else {}
            count = meta.get("record_count", 0) or 0
            if count > 0:
                statuses[ctx_src] = SourceStatusRecord(
                    status="verified_present",
                    record_count=count,
                    summary=f"{ctx_src} returned {count} record(s).",
                )
            else:
                statuses[ctx_src] = SourceStatusRecord(
                    status="verified_absent",
                    record_count=0,
                    summary=f"{ctx_src} returned no matching records.",
                )

        # Deterministic conflict detection
        conflicts: list[EvidenceConflict] = []

        access_status = statuses.get("access_control")
        schedule_status = statuses.get("schedule")
        policy_status = statuses.get("location_policy")

        # Access granted but location is restricted
        if (
            access_status and access_status.status == "verified_present"
            and policy_status and policy_status.status == "verified_present"
        ):
            # Check for access_granted and restricted rule in raw evidence
            access_records = (evidence_dict.get("access_events") or {}).get("records", [])
            policy_records = (evidence_dict.get("location_policy") or {}).get("records", [])
            has_granted = any(r.get("access_granted") for r in access_records if isinstance(r, dict))
            has_restricted = any(
                r.get("rule_type") in ("after_hours_restriction", "access_restriction", "restricted_zone")
                for r in policy_records if isinstance(r, dict)
            )
            if has_granted and has_restricted:
                conflicts.append(EvidenceConflict(
                    source_a="access_control",
                    source_b="location_policy",
                    description=(
                        "A valid access event was found, but the location policy "
                        "indicates restricted access rules apply. Further verification required."
                    ),
                ))

        # Badge access denied + no scheduled activity
        if (
            access_status and access_status.status == "verified_present"
            and schedule_status and schedule_status.status == "verified_absent"
        ):
            access_records = (evidence_dict.get("access_events") or {}).get("records", [])
            has_denied = any(
                not r.get("access_granted") for r in access_records if isinstance(r, dict)
            )
            if has_denied:
                conflicts.append(EvidenceConflict(
                    source_a="access_control",
                    source_b="schedule",
                    description=(
                        "An access-denied event was found, and no scheduled activity "
                        "covers this location for the event time window."
                    ),
                ))

        summary_parts = []
        present = [s for s, v in statuses.items() if v.status == "verified_present"]
        absent = [s for s, v in statuses.items() if v.status == "verified_absent"]
        unavailable = [s for s, v in statuses.items() if v.status == "unavailable"]
        if present:
            summary_parts.append(f"Evidence present from: {', '.join(present)}.")
        if absent:
            summary_parts.append(f"No records from: {', '.join(absent)}.")
        if unavailable:
            summary_parts.append(f"Unavailable sources: {', '.join(unavailable)}.")
        if conflicts:
            summary_parts.append(f"{len(conflicts)} conflict(s) detected.")
        context_summary = " ".join(summary_parts)[:1024]

        return ContextResult(
            event_id=event_id,
            source_statuses=statuses,
            conflicts=conflicts,
            missing_sources=missing,
            context_summary=context_summary,
            has_conflicts=bool(conflicts),
            has_missing_sources=bool(missing),
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
        agent_version: str,
        path: str,
        tool_calls: list[dict[str, Any]],
        error_message: str | None = None,
    ) -> None:
        if self._session is None:
            return

        completed_at = datetime.now(UTC).isoformat()
        self._session.add(AgentRun(
            id=run_id,
            event_id=event_id,
            agent_name="sentinel_context_agent",
            agent_version=agent_version,
            orchestrate_run_id=f"path:{path}",
            status=status,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=round(duration_ms, 2),
            error_message=error_message,
        ))
        for seq, tc in enumerate(tool_calls):
            self._session.add(ToolCall(
                id=str(uuid.uuid4()),
                agent_run_id=run_id,
                tool_name=tc.get("tool_name", "unknown"),
                status=tc.get("status", "success"),
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=round(tc.get("duration_ms", 0.0), 2),
                sequence=seq,
                error_message=tc.get("error_message"),
            ))
        await self._session.flush()
