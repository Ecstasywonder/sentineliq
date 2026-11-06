"""Agent telemetry failures must not poison the assessment transaction."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.context_service as context_module
import app.services.triage_service as triage_module
from app.models.agent_run import AgentRun
from app.models.event import SecurityEvent
from app.services.context_service import ContextService
from app.services.triage_service import TriageService

pytestmark = pytest.mark.asyncio


def _event() -> SecurityEvent:
    event_id = str(uuid.uuid4())
    return SecurityEvent(
        id=event_id,
        provider_event_id=f"provider-{event_id}",
        source_adapter="simulator",
        event_type="person_detected",
        event_timestamp="2026-11-06T12:00:00Z",
        location_id="telemetry-test-location",
        status="normalised",
    )


def _existing_run(run_id: str, event_id: str, agent_name: str) -> AgentRun:
    return AgentRun(
        id=run_id,
        event_id=event_id,
        agent_name=agent_name,
        agent_version="existing",
        orchestrate_run_id="path:test",
        status="success",
        started_at="2026-11-06T12:00:00+00:00",
    )


async def _assert_savepoint_isolation(
    db_session: AsyncSession,
    *,
    service,
    event_id: str,
    persist_kwargs: dict,
) -> None:
    fixed_run_id = str(uuid.uuid4())
    started_at = "2026-11-06T12:00:00+00:00"

    await service._persist_agent_run(
        run_id=fixed_run_id,
        event_id=event_id,
        started_at=started_at,
        status="success",
        duration_ms=1.0,
        path="deterministic",
        tool_calls=[],
        **persist_kwargs,
    )
    # Duplicate PK forces the telemetry insert to fail inside its SAVEPOINT.
    # The helper must swallow it and leave the outer transaction usable.
    await service._persist_agent_run(
        run_id=fixed_run_id,
        event_id=event_id,
        started_at=started_at,
        status="success",
        duration_ms=2.0,
        path="deterministic",
        tool_calls=[],
        **persist_kwargs,
    )
    await service._persist_agent_run(
        run_id=str(uuid.uuid4()),
        event_id=event_id,
        started_at=started_at,
        status="success",
        duration_ms=3.0,
        path="deterministic",
        tool_calls=[],
        **persist_kwargs,
    )

    count = await db_session.scalar(
        select(func.count())
        .select_from(AgentRun)
        .where(AgentRun.event_id == event_id)
    )
    assert count == 2


async def test_triage_telemetry_failure_isolated_by_savepoint(
    db_session: AsyncSession,
) -> None:
    event = _event()
    db_session.add(event)
    await db_session.flush()
    service = TriageService(db_session)

    await _assert_savepoint_isolation(
        db_session,
        service=service,
        event_id=event.id,
        persist_kwargs={
            "agent_name": "sentinel_triage_agent",
            "agent_version": "test",
        },
    )


async def test_context_telemetry_failure_isolated_by_savepoint(
    db_session: AsyncSession,
) -> None:
    event = _event()
    db_session.add(event)
    await db_session.flush()
    service = ContextService(db_session)

    await _assert_savepoint_isolation(
        db_session,
        service=service,
        event_id=event.id,
        persist_kwargs={
            "agent_version": "test",
        },
    )


async def test_triage_result_survives_telemetry_collision(
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    event = _event()
    fixed_run_uuid = uuid.uuid4()
    db_session.add_all(
        [
            event,
            _existing_run(str(fixed_run_uuid), event.id, "sentinel_triage_agent"),
        ]
    )
    await db_session.flush()

    monkeypatch.setattr(triage_module.uuid, "uuid4", lambda: fixed_run_uuid)
    service = TriageService(db_session)
    service._settings = SimpleNamespace(
        orchestrate_active=False,
        watsonx_active=False,
        agent_invoke_timeout=1.0,
    )

    result = await service.run(
        event.id,
        {
            "event_type": event.event_type,
            "event_timestamp": event.event_timestamp,
            "location_id": event.location_id,
        },
    )

    assert result.source == "deterministic_fallback"
    assert result.agent_run_id == str(fixed_run_uuid)


async def test_context_result_survives_telemetry_collision(
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    event = _event()
    fixed_run_uuid = uuid.uuid4()
    db_session.add_all(
        [
            event,
            _existing_run(str(fixed_run_uuid), event.id, "sentinel_context_agent"),
        ]
    )
    await db_session.flush()

    monkeypatch.setattr(context_module.uuid, "uuid4", lambda: fixed_run_uuid)
    service = ContextService(db_session)
    service._settings = SimpleNamespace(
        orchestrate_active=False,
        watsonx_active=False,
        agent_invoke_timeout=1.0,
    )

    result = await service.run(
        event_id=event.id,
        event_metadata={
            "event_type": event.event_type,
            "event_timestamp": event.event_timestamp,
            "location_id": event.location_id,
        },
        required_context=[],
        evidence={},
    )

    assert result.source == "deterministic_fallback"
    assert result.agent_run_id == str(fixed_run_uuid)
