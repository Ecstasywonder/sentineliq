"""Gate 4 simulator and Gate 3 repository contract tests."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import SecurityEvent
from app.models.incident import IncidentHistory
from app.repositories.events import IncidentRepository, SecurityEventRepository
from app.services.assessment_service import AssessmentService
from app.services.simulator import (
    demo_assessment_profile,
    demo_evidence_bundle,
    event_payload,
    load_scenarios,
    persist_scenarios,
    select_scenarios,
)
from app.api.v1.endpoints import simulator as simulator_endpoints

_CANONICAL_RISK_WEIGHTS = {
    "no_matching_badge": 25.0,
    "outside_schedule": 20.0,
    "restricted_area": 25.0,
    "no_work_order": 15.0,
    "recent_incidents": 10.0,
    "forced_door_alarm": 40.0,
    "approved_maintenance": -30.0,
    "valid_access_schedule": -35.0,
}


def _demo_event(scenario: dict, *, source_adapter: str = "simulator") -> SecurityEvent:
    payload = event_payload(scenario)
    raw_metadata = payload.pop("raw_metadata", {})
    return SecurityEvent(
        id=f"event-{scenario['id']}",
        source_adapter=source_adapter,
        normalised_data=json.dumps({"scenario_id": scenario["id"]}),
        raw_metadata=json.dumps(raw_metadata),
        status="normalised",
        **payload,
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
        assert scenario.get("demo_assessment_profile"), (
            f"{sid} must define trusted, event-isolated demo evidence"
        )


def test_demo_profile_is_server_owned_and_raw_metadata_cannot_enable_it() -> None:
    scenario = select_scenarios(["demo-scenario-e"])[0]
    trusted = _demo_event(scenario)
    assert demo_assessment_profile(trusted)["simulate_ai_unavailable"] is True

    ordinary = _demo_event(scenario, source_adapter="camera_adapter")
    assert demo_assessment_profile(ordinary) is None

    # A public event can carry scenario-looking raw metadata, but it has no
    # server-written scenario_id in normalised_data and must not gain controls.
    ordinary.source_adapter = "simulator"
    ordinary.normalised_data = json.dumps({"event_type": ordinary.event_type})
    ordinary.raw_metadata = json.dumps(
        {"scenario_id": "demo-scenario-e", "simulate_ai_unavailable": True}
    )
    assert demo_assessment_profile(ordinary) is None


@pytest.mark.parametrize(
    ("scenario_id", "expected_level"),
    [
        ("demo-scenario-a", "low"),
        ("demo-scenario-b", "critical"),
        ("demo-scenario-c", "medium"),
        ("demo-scenario-d", "high"),
        ("demo-scenario-e", "medium"),
    ],
)
@pytest.mark.asyncio
async def test_demo_profiles_drive_claimed_canonical_risk(
    db_session: AsyncSession,
    scenario_id: str,
    expected_level: str,
) -> None:
    scenario = select_scenarios([scenario_id])[0]
    event = _demo_event(scenario)
    profile = demo_assessment_profile(event)
    assert profile is not None
    evidence = demo_evidence_bundle(event, profile)
    errors = AssessmentService(db_session)._normalize_evidence_errors(evidence.errors)
    signals = AssessmentService(db_session)._build_signals(
        evidence,
        event,
        unavailable_source_ids=set(errors),
    )
    triggered = {signal.factor_id for signal in signals if signal.triggered}
    score = sum(
        weight
        for factor_id, weight in _CANONICAL_RISK_WEIGHTS.items()
        if factor_id in triggered
    )
    score = max(0.0, min(200.0, score))
    if score >= 75:
        actual_level = "critical"
    elif score >= 50:
        actual_level = "high"
    elif score >= 25:
        actual_level = "medium"
    else:
        actual_level = "low"
    assert actual_level == expected_level

    if scenario_id == "demo-scenario-c":
        assert "no_matching_badge" not in triggered
        assert "outside_schedule" not in triggered
        assert set(errors) == {"mock_access_control", "mock_schedule"}


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
async def test_persist_scenarios_instance_id_creates_fresh_event(
    db_session: AsyncSession,
) -> None:
    scenarios = select_scenarios(["demo-scenario-a"])
    first = await persist_scenarios(
        db_session,
        scenarios,
        dedup_window_seconds=3600,
        instance_id="run-one",
    )
    second = await persist_scenarios(
        db_session,
        scenarios,
        dedup_window_seconds=3600,
        instance_id="run-two",
    )
    assert first[0][2] is False
    assert second[0][2] is False
    assert first[0][1].id != second[0][1].id


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

    fresh = await client.post(
        "/api/v1/simulator/generate",
        json={"scenario_ids": ["forced-door-alarm"], "instance_id": "fresh-run"},
    )
    assert fresh.status_code == 200
    assert fresh.json()["persisted"] == 1


@pytest.mark.asyncio
async def test_simulator_api_is_hidden_when_disabled(client, monkeypatch) -> None:
    monkeypatch.setattr(
        simulator_endpoints,
        "get_settings",
        lambda: SimpleNamespace(enable_simulator_api=False),
    )

    response = await client.post(
        "/api/v1/simulator/generate",
        json={"scenario_ids": ["demo-scenario-a"], "persist": False},
    )

    assert response.status_code == 404
