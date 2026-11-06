"""Authenticated API for previewing or loading deterministic MVP scenarios."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_db
from app.schemas.simulator import (
    SimulatorEventResponse,
    SimulatorGenerateRequest,
    SimulatorGenerateResponse,
)
from app.security.dependencies import require_permission
from app.services.simulator import (
    UnknownScenarioError,
    event_payload,
    persist_scenarios,
    select_scenarios,
)

router = APIRouter()


@router.post(
    "/generate",
    response_model=SimulatorGenerateResponse,
    dependencies=[Depends(require_permission("events:ingest"))],
    summary="Generate deterministic MVP security-event scenarios",
)
async def generate_scenarios(
    payload: SimulatorGenerateRequest,
    session: AsyncSession = Depends(get_db),
) -> SimulatorGenerateResponse:
    try:
        scenarios = select_scenarios(payload.scenario_ids)
    except UnknownScenarioError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if not payload.persist:
        return SimulatorGenerateResponse(
            generated=len(scenarios),
            persisted=0,
            duplicates=0,
            events=[
                SimulatorEventResponse(
                    scenario_id=scenario["id"], title=scenario["title"], event=event_payload(scenario)
                )
                for scenario in scenarios
            ],
        )

    rows = await persist_scenarios(
        session, scenarios, dedup_window_seconds=get_settings().event_dedup_window_seconds
    )
    return SimulatorGenerateResponse(
        generated=len(rows),
        persisted=sum(not duplicate for _, _, duplicate in rows),
        duplicates=sum(duplicate for _, _, duplicate in rows),
        events=[
            SimulatorEventResponse(
                scenario_id=scenario["id"],
                title=scenario["title"],
                event=event_payload(scenario),
                persisted_event_id=event.id,
                duplicate=duplicate,
            )
            for scenario, event, duplicate in rows
        ],
    )
