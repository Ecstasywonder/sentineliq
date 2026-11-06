"""Contracts for the deterministic MVP event simulator."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SimulatorGenerateRequest(BaseModel):
    """Select scenarios by stable scenario ID; omission generates the full suite."""

    scenario_ids: list[str] | None = Field(default=None, min_length=1, max_length=100)
    persist: bool = Field(default=True, description="Persist events; false previews only.")


class SimulatorEventResponse(BaseModel):
    scenario_id: str
    title: str
    event: dict[str, Any]
    persisted_event_id: str | None = None
    duplicate: bool = False


class SimulatorGenerateResponse(BaseModel):
    generated: int
    persisted: int
    duplicates: int
    events: list[SimulatorEventResponse]
