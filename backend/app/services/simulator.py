"""Deterministic scenario loading and event generation for MVP demonstrations."""

from __future__ import annotations

import json
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import SecurityEvent
from app.repositories.events import SecurityEventRepository
from app.schemas.events import EventIngestRequest
from app.schemas.tools import AggregatedEvidence

SCENARIO_PATH = Path(__file__).resolve().parents[3] / "data" / "scenarios" / "mvp-scenarios.json"


class UnknownScenarioError(ValueError):
    """Raised when a caller selects an ID absent from the versioned dataset."""


_DEMO_PROFILE_VALUES = {
    "access": {"granted", "denied", "absent", "unavailable"},
    "schedule": {"present", "absent", "unavailable"},
    "work_order": {"present", "absent", "unavailable"},
    "policy": {"restricted", "standard", "unavailable"},
    "incidents": {"present", "absent", "unavailable"},
}


def load_scenarios() -> list[dict[str, Any]]:
    """Load and minimally validate the checked-in, deterministic scenario fixture."""
    scenarios = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError("Simulator dataset must be a non-empty JSON list.")
    ids = [item.get("id") for item in scenarios]
    if len(ids) != len(set(ids)) or any(not isinstance(item, str) for item in ids):
        raise ValueError("Simulator scenario IDs must be unique non-empty strings.")
    for scenario in scenarios:
        event = scenario.get("event")
        if not isinstance(event, dict) or not all(
            event.get(field)
            for field in ("provider_event_id", "event_type", "event_timestamp", "location_id")
        ):
            raise ValueError(f"Scenario {scenario['id']} has an invalid event payload.")
        # Reuse the public ingestion contract so simulator fixtures cannot drift
        # into a shape the production event endpoint would reject.
        EventIngestRequest.model_validate(event)
        profile = scenario.get("demo_assessment_profile")
        if profile is not None:
            if not isinstance(profile, dict) or set(profile) - {
                *_DEMO_PROFILE_VALUES,
                "simulate_ai_unavailable",
            }:
                raise ValueError(f"Scenario {scenario['id']} has an invalid demo profile.")
            for key, allowed in _DEMO_PROFILE_VALUES.items():
                if profile.get(key) not in allowed:
                    raise ValueError(f"Scenario {scenario['id']} demo profile has invalid {key}.")
            if not isinstance(profile.get("simulate_ai_unavailable", False), bool):
                raise ValueError(f"Scenario {scenario['id']} demo profile has invalid AI control.")
    return scenarios


def select_scenarios(scenario_ids: list[str] | None = None) -> list[dict[str, Any]]:
    scenarios = load_scenarios()
    if scenario_ids is None:
        return scenarios
    indexed = {scenario["id"]: scenario for scenario in scenarios}
    unknown = [scenario_id for scenario_id in scenario_ids if scenario_id not in indexed]
    if unknown:
        raise UnknownScenarioError(f"Unknown simulator scenario IDs: {', '.join(unknown)}")
    return [indexed[scenario_id] for scenario_id in scenario_ids]


def event_payload(scenario: dict[str, Any]) -> dict[str, Any]:
    """Return a caller-safe copy; generation never mutates the source dataset."""
    return dict(scenario["event"])


async def persist_scenarios(
    session: AsyncSession,
    scenarios: list[dict[str, Any]],
    *,
    dedup_window_seconds: int,
    instance_id: str | None = None,
) -> list[tuple[dict[str, Any], SecurityEvent, bool]]:
    """Persist selected fixtures idempotently using their stable provider IDs."""
    repository = SecurityEventRepository(session)
    persisted: list[tuple[dict[str, Any], SecurityEvent, bool]] = []
    for scenario in scenarios:
        payload = event_payload(scenario)
        if instance_id:
            payload["provider_event_id"] = f"{payload['provider_event_id']}-{instance_id}"
        duplicate = await repository.find_recent_by_provider_id(
            payload["provider_event_id"], within_seconds=dedup_window_seconds
        )
        if duplicate is not None:
            persisted.append((scenario, duplicate, True))
            continue
        raw_metadata = payload.pop("raw_metadata", {})
        event = SecurityEvent(
            id=str(uuid.uuid4()),
            **payload,
            source_adapter="simulator",
            status="normalised",
            normalised_data=json.dumps(
                {
                    "scenario_id": scenario["id"],
                    "scenario_instance_id": instance_id,
                    **payload,
                }
            ),
            raw_metadata=json.dumps(raw_metadata),
        )
        await repository.add(event)
        persisted.append((scenario, event, False))
    return persisted


def demo_assessment_profile(event: SecurityEvent) -> dict[str, Any] | None:
    """Return a trusted, versioned demo profile for a simulator-created event.

    The event stores only the scenario identifier.  Profile contents are always
    reloaded from the checked-in scenario catalogue and never from
    ``raw_metadata`` or caller-supplied normalised data.  Ordinary ingested
    events therefore cannot activate demo evidence or failure controls.
    """
    if event.source_adapter != "simulator" or not event.normalised_data:
        return None
    try:
        normalised = json.loads(event.normalised_data)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(normalised, dict):
        return None
    scenario_id = normalised.get("scenario_id")
    if not isinstance(scenario_id, str):
        return None
    try:
        scenario = select_scenarios([scenario_id])[0]
    except (UnknownScenarioError, ValueError):
        return None
    profile = scenario.get("demo_assessment_profile")
    return deepcopy(profile) if isinstance(profile, dict) else None


def demo_evidence_bundle(
    event: SecurityEvent,
    profile: dict[str, Any],
) -> AggregatedEvidence:
    """Build isolated evidence from a validated, server-owned demo profile.

    Demo evidence is in-memory and event-bound.  It does not insert shared
    access, schedule, or incident rows, so repeated demonstrations cannot
    contaminate later assessments or ordinary production evidence queries.
    """
    event_id = str(event.id)
    timestamp = event.event_timestamp
    location_id = event.location_id
    facility_id = event.facility_id

    def meta(source: str, count: int) -> dict[str, Any]:
        return {"source": source, "record_count": count, "truncated": False}

    errors: dict[str, str] = {}

    access_state = profile["access"]
    if access_state == "unavailable":
        access = None
        errors["access_events"] = "Demo source unavailable"
    else:
        access_records = []
        if access_state in {"granted", "denied"}:
            granted = access_state == "granted"
            access_records.append(
                {
                    "id": f"demo-access-{event_id}",
                    "location_id": location_id,
                    "facility_id": facility_id,
                    "badge_id": "demo-authorized-badge" if granted else None,
                    "person_ref": "demo-subject",
                    "access_type": "entry" if granted else "denied",
                    "access_granted": granted,
                    "occurred_at": timestamp,
                    "source_system": "simulator_fixture",
                }
            )
        access = {
            "meta": meta("mock_access_control", len(access_records)),
            "records": access_records,
        }

    schedule_state = profile["schedule"]
    if schedule_state == "unavailable":
        schedule = None
        errors["schedule"] = "Demo source unavailable"
    else:
        schedule_records = []
        if schedule_state == "present":
            schedule_records.append(
                {
                    "id": f"demo-schedule-{event_id}",
                    "facility_id": facility_id,
                    "location_id": location_id,
                    "schedule_type": "employee",
                    "person_ref": "demo-subject",
                    "description": "Versioned simulator schedule fixture",
                    "start_time": timestamp,
                    "end_time": timestamp,
                    "is_active": True,
                    "source_system": "simulator_fixture",
                }
            )
        schedule = {
            "meta": meta("mock_schedule", len(schedule_records)),
            "records": schedule_records,
        }

    work_order_state = profile["work_order"]
    if work_order_state == "unavailable":
        work_orders = None
        errors["work_orders"] = "Demo source unavailable"
    else:
        work_order_records = []
        if work_order_state == "present":
            work_order_records.append(
                {
                    "id": f"demo-work-order-{event_id}",
                    "facility_id": facility_id,
                    "location_id": location_id,
                    "work_order_number": f"DEMO-{event_id[:12]}",
                    "description": "Versioned simulator work-order fixture",
                    "assigned_to": "demo-subject",
                    "scheduled_start": timestamp,
                    "scheduled_end": timestamp,
                    "status": "open",
                    "requires_after_hours": False,
                    "approved_by": "demo-supervisor",
                    "source_system": "simulator_fixture",
                }
            )
        work_orders = {
            "meta": meta("mock_work_order", len(work_order_records)),
            "records": work_order_records,
        }

    policy_state = profile["policy"]
    if policy_state == "unavailable":
        policy = None
        errors["location_policy"] = "Demo source unavailable"
    else:
        policy_records = []
        if policy_state == "restricted":
            policy_records.append(
                {
                    "id": f"demo-policy-{event_id}",
                    "facility_id": facility_id,
                    "location_id": location_id,
                    "rule_code": f"DEMO-RESTRICTED-{event_id[:12]}",
                    "rule_type": "restricted_zone",
                    "description": "Versioned simulator restricted-zone fixture",
                    "is_active": True,
                    "policy_reference": "DEMO-POLICY",
                }
            )
        policy = {
            "meta": meta("db_security_rules", len(policy_records)),
            "records": policy_records,
        }

    incident_state = profile["incidents"]
    if incident_state == "unavailable":
        incidents = None
        errors["incident_history"] = "Demo source unavailable"
    else:
        incident_records = []
        if incident_state == "present":
            incident_records.append(
                {
                    "id": f"demo-incident-{event_id}",
                    "facility_id": facility_id,
                    "location_id": location_id,
                    "incident_code": f"DEMO-INC-{event_id[:12]}",
                    "incident_type": "unauthorized_access_attempt",
                    "severity": "high",
                    "occurred_at": timestamp,
                    "description": "Versioned simulator incident-history fixture",
                    "resolved": True,
                }
            )
        incidents = {
            "meta": meta("db_incident_history", len(incident_records)),
            "records": incident_records,
        }

    # Delivery is not relevant to the five Gate 23 scenarios, but it remains
    # an available source so confidence reflects the intended scenario rather
    # than an omitted fixture field.
    delivery = {"meta": meta("mock_delivery", 0), "records": []}
    integration_health = {
        "meta": meta("db_integration_health", 0),
        "records": [],
    }

    return AggregatedEvidence.model_validate(
        {
            "event_id": event_id,
            "access_events": access,
            "schedule": schedule,
            "work_orders": work_orders,
            "delivery": delivery,
            "location_policy": policy,
            "incident_history": incidents,
            "integration_health": integration_health,
            "errors": errors,
        }
    )
