"""Deterministic scenario loading and event generation for MVP demonstrations."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import SecurityEvent
from app.repositories.events import SecurityEventRepository
from app.schemas.events import EventIngestRequest

SCENARIO_PATH = Path(__file__).resolve().parents[3] / "data" / "scenarios" / "mvp-scenarios.json"


class UnknownScenarioError(ValueError):
    """Raised when a caller selects an ID absent from the versioned dataset."""


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
            event.get(field) for field in ("provider_event_id", "event_type", "event_timestamp", "location_id")
        ):
            raise ValueError(f"Scenario {scenario['id']} has an invalid event payload.")
        # Reuse the public ingestion contract so simulator fixtures cannot drift
        # into a shape the production event endpoint would reject.
        EventIngestRequest.model_validate(event)
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
    session: AsyncSession, scenarios: list[dict[str, Any]], *, dedup_window_seconds: int
) -> list[tuple[dict[str, Any], SecurityEvent, bool]]:
    """Persist selected fixtures idempotently using their stable provider IDs."""
    repository = SecurityEventRepository(session)
    persisted: list[tuple[dict[str, Any], SecurityEvent, bool]] = []
    for scenario in scenarios:
        payload = event_payload(scenario)
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
            normalised_data=json.dumps({"scenario_id": scenario["id"], **payload}),
            raw_metadata=json.dumps(raw_metadata),
        )
        await repository.add(event)
        persisted.append((scenario, event, False))
    return persisted
