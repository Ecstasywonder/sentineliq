"""
Application configuration — loaded from environment variables.
All settings have explicit types and defaults.
Secrets are NEVER committed — use .env file (see .env.example).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -------------------------------------------------------------------------
    # Application
    # -------------------------------------------------------------------------
    app_env: Literal["development", "staging", "production"] = "development"
    app_name: str = "SentinelIQ"
    app_version: str = "0.1.0"
    debug: bool = False
    log_level: str = "INFO"

    # -------------------------------------------------------------------------
    # Database
    # -------------------------------------------------------------------------
    database_url: str = Field(
        default="postgresql+asyncpg://sentineliq:changeme@localhost:5432/sentineliq",
        description="Async SQLAlchemy connection string",
    )
    database_url_sync: str = Field(
        default="postgresql://sentineliq:changeme@localhost:5432/sentineliq",
        description="Sync connection string (for Alembic migrations)",
    )
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30

    # -------------------------------------------------------------------------
    # Security / Auth
    # -------------------------------------------------------------------------
    secret_key: str = Field(
        default="CHANGE_ME_INSECURE_DEFAULT",
        description="JWT signing key — must be set via environment in production",
    )
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 7

    # -------------------------------------------------------------------------
    # IBM watsonx Orchestrate
    # -------------------------------------------------------------------------
    orchestrate_base_url: str = ""
    orchestrate_api_key: str = ""
    orchestrate_space_id: str = ""

    # -------------------------------------------------------------------------
    # CORS
    # -------------------------------------------------------------------------
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v

    # -------------------------------------------------------------------------
    # Event processing
    # -------------------------------------------------------------------------
    event_dedup_window_seconds: int = 300
    access_correlation_window_minutes: int = 10
    max_incident_history_results: int = 10
    max_evidence_age_hours: int = 24

    # -------------------------------------------------------------------------
    # Risk / Confidence engine
    # -------------------------------------------------------------------------
    active_risk_policy_version: str = "1.0"

    # ADR-006: This value is RESERVED FOR FUTURE USE only.
    # It MUST NOT be used to auto-dismiss, auto-close, or auto-approve any event.
    # Any use for automated decision-making requires a new ADR and product-owner approval.
    min_confidence_auto_clear: float = 0.85

    # -------------------------------------------------------------------------
    # Feature flags
    # -------------------------------------------------------------------------
    enable_semantic_search: bool = True
    enable_agent_tracing: bool = True
    enable_rate_limiting: bool = True

    # -------------------------------------------------------------------------
    # Rate limiting
    # -------------------------------------------------------------------------
    rate_limit_events_per_minute: int = 100
    rate_limit_api_per_minute: int = 300

    # -------------------------------------------------------------------------
    # Observability
    # -------------------------------------------------------------------------
    enable_structured_logging: bool = True
    enable_request_logging: bool = True
    otel_endpoint: str = ""

    # -------------------------------------------------------------------------
    # Storage
    # -------------------------------------------------------------------------
    media_storage_backend: str = "local"
    media_local_path: str = "/app/media"

    # -------------------------------------------------------------------------
    # Adapter selection
    # -------------------------------------------------------------------------
    access_control_adapter: str = "mock"
    schedule_adapter: str = "mock"
    work_order_adapter: str = "mock"
    delivery_adapter: str = "mock"
    visitor_adapter: str = "mock"
    event_source_adapter: str = "simulator"


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings singleton."""
    return Settings()
