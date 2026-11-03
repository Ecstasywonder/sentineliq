"""
System health endpoint — additional API-level detail.
The primary /health and /ready endpoints live in app/main.py.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.config import get_settings

router = APIRouter()
settings = get_settings()


@router.get("/info", summary="Application info")
async def app_info() -> JSONResponse:
    return JSONResponse(
        content={
            "service": settings.app_name,
            "version": settings.app_version,
            "environment": settings.app_env,
            "features": {
                "semantic_search": settings.enable_semantic_search,
                "agent_tracing": settings.enable_agent_tracing,
                "rate_limiting": settings.enable_rate_limiting,
            },
        }
    )
