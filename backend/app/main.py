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
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_v1_router
from app.config import get_settings
from app.db.session import check_db_connection, engine
from app.logging_config import configure_logging
from app.security.rate_limit import (
    SlidingWindowRateLimiter,
    request_identity,
    request_peer_identity,
)
from app.security.request_limits import RequestBodyLimitMiddleware

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

    app.add_middleware(
        RequestBodyLimitMiddleware,
        max_body_size=settings.max_request_body_bytes,
    )

    # -----------------------------------------------------------------------
    # Application rate limiting
    # -----------------------------------------------------------------------
    limiter = SlidingWindowRateLimiter()
    app.state.rate_limiter = limiter

    @app.middleware("http")
    async def rate_limiting(request: Request, call_next: object) -> Response:
        if not settings.enable_rate_limiting or not request.url.path.startswith("/api/v1"):
            return await call_next(request)  # type: ignore[arg-type]

        identity = request_identity(request)
        checks = [("api", identity, settings.rate_limit_api_per_minute)]
        if request.method == "POST" and request.url.path == "/api/v1/events":
            checks.append(
                ("event_ingestion", identity, settings.rate_limit_events_per_minute)
            )
        if request.method == "POST" and request.url.path in {
            "/api/v1/auth/token",
            "/api/v1/auth/refresh",
        }:
            # Never let an optional bearer header shift login/refresh attempts
            # into another principal's bucket.
            checks.append(
                (
                    "authentication",
                    request_peer_identity(request),
                    settings.rate_limit_auth_per_minute,
                )
            )

        tightest = None
        for scope, scope_identity, limit in checks:
            decision = await limiter.check(scope, scope_identity, limit)
            if not decision.allowed:
                logger.warning(
                    "http.rate_limited",
                    scope=scope,
                    peer=request.client.host if request.client else "unknown",
                    path=request.url.path,
                )
                return JSONResponse(
                    status_code=429,
                    headers={
                        "Retry-After": str(decision.retry_after),
                        "X-RateLimit-Limit": str(decision.limit),
                        "X-RateLimit-Remaining": "0",
                    },
                    content={
                        "detail": {
                            "code": "RATE_LIMITED",
                            "message": "Too many requests. Retry after the indicated delay.",
                        }
                    },
                )
            if tightest is None or decision.remaining < tightest.remaining:
                tightest = decision

        response: Response = await call_next(request)  # type: ignore[arg-type]
        if tightest is not None:
            response.headers["X-RateLimit-Limit"] = str(tightest.limit)
            response.headers["X-RateLimit-Remaining"] = str(tightest.remaining)
        return response

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
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
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
