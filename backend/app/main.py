"""
SentinelIQ — FastAPI application entry point.

Responsibilities:
- Application factory
- Middleware registration (CORS, logging, security headers)
- Router mounting
- Startup / shutdown lifecycle hooks
- Health and readiness endpoints
"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db.session import engine, check_db_connection
from app.logging_config import configure_logging
from app.api.v1.router import api_v1_router

settings = get_settings()
configure_logging()
logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Lifespan (startup / shutdown)
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info(
        "sentineliq.startup",
        version=settings.app_version,
        env=settings.app_env,
    )
    yield
    logger.info("sentineliq.shutdown")
    await engine.dispose()


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------
def create_app() -> FastAPI:
    app = FastAPI(
        title="SentinelIQ API",
        description=(
            "AI Security Decision Intelligence — "
            "evidence-backed, human-supervised security recommendations."
        ),
        version=settings.app_version,
        docs_url="/docs" if settings.app_env != "production" else None,
        redoc_url="/redoc" if settings.app_env != "production" else None,
        openapi_url="/openapi.json" if settings.app_env != "production" else None,
        lifespan=lifespan,
    )

    # -----------------------------------------------------------------------
    # CORS
    # -----------------------------------------------------------------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # -----------------------------------------------------------------------
    # Security headers middleware
    # -----------------------------------------------------------------------
    @app.middleware("http")
    async def security_headers(request: Request, call_next: object) -> Response:
        response: Response = await call_next(request)  # type: ignore[arg-type]
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if settings.app_env == "production":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        return response

    # -----------------------------------------------------------------------
    # Request logging middleware
    # -----------------------------------------------------------------------
    if settings.enable_request_logging:

        @app.middleware("http")
        async def request_logging(request: Request, call_next: object) -> Response:
            start = time.perf_counter()
            response: Response = await call_next(request)  # type: ignore[arg-type]
            duration_ms = (time.perf_counter() - start) * 1000
            logger.info(
                "http.request",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=round(duration_ms, 2),
            )
            return response

    # -----------------------------------------------------------------------
    # Routers
    # -----------------------------------------------------------------------
    app.include_router(api_v1_router, prefix="/api/v1")

    # -----------------------------------------------------------------------
    # Health / readiness endpoints (outside versioned prefix)
    # -----------------------------------------------------------------------
    @app.get("/health", tags=["System"], summary="Liveness check")
    async def health() -> JSONResponse:
        return JSONResponse(
            content={
                "status": "ok",
                "service": settings.app_name,
                "version": settings.app_version,
            }
        )

    @app.get("/ready", tags=["System"], summary="Readiness check")
    async def ready() -> JSONResponse:
        db_ok, db_message = await check_db_connection()
        if db_ok:
            return JSONResponse(
                content={
                    "status": "ready",
                    "database": "connected",
                    "migrations": "pending_verification",
                }
            )
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "database": db_message,
            },
        )

    return app


app = create_app()
