"""Gate 4 simulator and Gate 3 repository contract tests."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.incident import IncidentHistory
from app.repositories.events import IncidentRepository, SecurityEventRepository
from app.services.simulator import (
    event_payload,
    load_scenarios,
    persist_scenarios,
    select_scenarios,
)


def test_dataset_covers_all_required_scenario_types() -> None:
    scenarios = load_scenarios()
    scenario_ids = {scenario["id"] for scenario in scenarios}
    # 19 original scenarios + 5 Gate 23 demo scenarios (A-E) = 24 total
    assert len(scenarios) == 24
    assert {
        "ordinary-employee-arrival",
        "authorized-maintenance",
        "authorized-after-hours-maintenance",
        "scheduled-delivery",
        "unscheduled-delivery",
        "restricted-zone-activity",
        "no-matching-badge",
        "failed-badge-lookup",
        "schedule-system-unavailable",
        "conflicting-access-schedule",
        "forced-door-alarm",
        "repeated-after-hours-activity",
        "low-risk-event",
        "medium-risk-event",
        "high-risk-event",
        "critical-risk-signal",
        "incomplete-metadata",
        "duplicated-event",
        "stale-evidence",
        # Gate 23 — MVP usability demo scenarios (§51)
        "demo-scenario-a",
        "demo-scenario-b",
        "demo-scenario-c",
        "demo-scenario-d",
        "demo-scenario-e",
    } == scenario_ids
    assert {scenario["expected_risk"] for scenario in scenarios} == {
        "low",
        "medium",
        "high",
        "critical",
    }
    assert event_payload(scenarios[0]) == event_payload(scenarios[0])


def test_gate23_demo_scenarios_present() -> None:
    """Gate 23: all five §51 demo scenarios are in the dataset and well-formed."""
    scenarios = load_scenarios()
    gate23 = {s["id"]: s for s in scenarios if s.get("gate23_scenario")}
    assert set(gate23) == {
        "demo-scenario-a",
        "demo-scenario-b",
        "demo-scenario-c",
        "demo-scenario-d",
        "demo-scenario-e",
    }, "All five Gate 23 demo scenarios must be present"
    labels = {s["gate23_scenario"] for s in gate23.values()}
    assert labels == {"A", "B", "C", "D", "E"}, "Gate 23 scenarios must be labelled A-E"
    # Each scenario must have a description and a valid event payload
    for sid, scenario in gate23.items():
        assert scenario.get("description"), f"{sid} must have a description"
        payload = event_payload(scenario)
        assert payload.get("provider_event_id"), f"{sid} must have a provider_event_id"
        assert payload.get("event_type"), f"{sid} must have an event_type"


def test_select_scenarios_rejects_unknown_id() -> None:
    with pytest.raises(ValueError, match="Unknown simulator scenario IDs"):
        select_scenarios(["not-a-scenario"])


@pytest.mark.asyncio
async def test_persist_scenarios_is_idempotent(db_session: AsyncSession) -> None:
    scenarios = select_scenarios(["ordinary-employee-arrival"])
    first = await persist_scenarios(db_session, scenarios, dedup_window_seconds=3600)
    second = await persist_scenarios(db_session, scenarios, dedup_window_seconds=3600)

    assert first[0][2] is False
    assert second[0][2] is True
    assert first[0][1].id == second[0][1].id


@pytest.mark.asyncio
async def test_repositories_scope_event_and_incident_queries(db_session: AsyncSession) -> None:
    scenario = select_scenarios(["ordinary-employee-arrival"])[0]
    event = (await persist_scenarios(db_session, [scenario], dedup_window_seconds=3600))[0][1]
    events = SecurityEventRepository(db_session)
    assert await events.get(event.id) is event

    incident = IncidentHistory(
        id="incident-repository-test",
        incident_code="INC-REPOSITORY-TEST",
        incident_type="access",
        severity="low",
        location_id="MAIN_ENTRANCE",
        occurred_at="2026-01-01T00:00:00Z",
        description="Repository test incident",
    )
    db_session.add(incident)
    await db_session.flush()
    assert (await IncidentRepository(db_session).by_location("MAIN_ENTRANCE"))[0].id == incident.id


@pytest.mark.asyncio
async def test_simulator_api_previews_and_idempotently_persists(client) -> None:
    preview = await client.post(
        "/api/v1/simulator/generate",
        json={"scenario_ids": ["forced-door-alarm"], "persist": False},
    )
    assert preview.status_code == 200
    assert preview.json()["persisted"] == 0

    first = await client.post(
        "/api/v1/simulator/generate",
        json={"scenario_ids": ["forced-door-alarm"]},
    )
    second = await client.post(
        "/api/v1/simulator/generate",
        json={"scenario_ids": ["forced-door-alarm"]},
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["persisted"] == 1
    assert second.json()["duplicates"] == 1
