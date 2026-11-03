"""Top-level API v1 router — mounts all resource routers."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import health as health_router

api_v1_router = APIRouter()

# Health sub-router (additional API-level health detail)
api_v1_router.include_router(
    health_router.router,
    prefix="/system",
    tags=["System"],
)
