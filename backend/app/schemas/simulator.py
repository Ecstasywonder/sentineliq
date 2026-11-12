"""Contracts for the deterministic MVP event simulator."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SimulatorGenerateRequest(BaseModel):
    """Select scenarios by stable scenario ID; omission generates the full suite."""

    scenario_ids: list[str] | None = Field(default=None, min_length=1, max_length=100)
    persist: bool = Field(default=True, description="Persist events; false previews only.")
    instance_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9._-]+$",
        description=(
            "Optional bounded run identifier appended to provider event IDs. "
            "This lets an authorised demo runner create a fresh, independently "
            "reviewable event without deleting or mutating an earlier run."
        ),
    )


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
