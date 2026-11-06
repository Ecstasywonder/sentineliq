"""Gate 4 simulator and Gate 3 repository contract tests."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.incident import IncidentHistory
from app.repositories.events import IncidentRepository, SecurityEventRepository
from app.services.simulator import event_payload, load_scenarios, persist_scenarios, select_scenarios


def test_dataset_covers_all_required_scenario_types() -> None:
    scenarios = load_scenarios()
    scenario_ids = {scenario["id"] for scenario in scenarios}
    assert len(scenarios) == 19
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
    } == scenario_ids
    assert {scenario["expected_risk"] for scenario in scenarios} == {
        "low", "medium", "high", "critical"
    }
    assert event_payload(scenarios[0]) == event_payload(scenarios[0])


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
