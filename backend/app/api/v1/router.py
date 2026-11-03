"""Top-level API v1 router — mounts all resource routers."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import auth as auth_router
from app.api.v1.endpoints import events as events_router
from app.api.v1.endpoints import health as health_router
from app.api.v1.endpoints import tools as tools_router

api_v1_router = APIRouter()

# Health sub-router (additional API-level health detail)
api_v1_router.include_router(
    health_router.router,
    prefix="/system",
    tags=["System"],
)

# Auth — login, refresh, me
api_v1_router.include_router(
    auth_router.router,
    prefix="/auth",
    tags=["Auth"],
)

# Events — ingestion, queue, lifecycle
api_v1_router.include_router(
    events_router.router,
    prefix="/events",
    tags=["Events"],
)

# Context tools — evidence retrieval (Gate 7, ADR-005 read-only adapters)
api_v1_router.include_router(
    tools_router.router,
    prefix="/tools",
    tags=["Tools"],
)
