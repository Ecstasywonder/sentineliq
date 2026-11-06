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
    # IBM watsonx Orchestrate (Path B — primary when provisioned)
    # -------------------------------------------------------------------------
    # Full tenant URL of the watsonx Orchestrate SaaS instance.
    # Format: https://<tenant>.ibm-watson-orchestrate.com
    # When set + orchestrate_api_key is set → Path B is active.
    # Leave empty to fall through to Path A (watsonx.ai direct).
    orchestrate_url: str = ""
    orchestrate_api_key: str = ""
    # Agent IDs as imported into Orchestrate (set after `orchestrate agents import`)
    orchestrate_triage_agent_id: str = "sentinel_triage_agent"
    orchestrate_context_agent_id: str = "sentinel_context_agent"
    orchestrate_explanation_agent_id: str = "sentinel_explanation_agent"
    orchestrate_coordinator_agent_id: str = "sentinel_coordinator"

    # -------------------------------------------------------------------------
    # IBM watsonx.ai (Path A — verified fallback)
    # -------------------------------------------------------------------------
    # Base URL for the watsonx.ai ML API.
    # Verified: https://us-south.ml.cloud.ibm.com
    watsonx_base_url: str = "https://us-south.ml.cloud.ibm.com"
    # IBM Cloud API key — same key works for both Orchestrate and watsonx.ai.
    # Used to obtain short-lived IAM bearer tokens.
    watsonx_api_key: str = ""
    # Space ID — must have a Watson Machine Learning instance associated.
    # Verified working: Orchestrate (Developer edition) space.
    watsonx_space_id: str = ""
    # Model used for agent calls via watsonx.ai Chat API.
    # Verified: ibm/granite-4-h-small supports text_chat.
    watsonx_model_id: str = "ibm/granite-4-h-small"

    # -------------------------------------------------------------------------
    # Agent invocation config (shared)
    # -------------------------------------------------------------------------
    # Timeout in seconds for a single agent/LLM call.
    agent_invoke_timeout: float = 45.0
    # Maximum retries before falling back to the next path.
    agent_max_retries: int = 1

    # ---------------------------------------------------------------------------
    # Backwards-compat shims (deprecated field names — will be removed in Gate 20)
    # Kept so existing .env files that still set ORCHESTRATE_BASE_URL /
    # ORCHESTRATE_SPACE_ID continue to work.
    # ---------------------------------------------------------------------------
    orchestrate_base_url: str = ""   # remapped → watsonx_base_url if set
    orchestrate_space_id: str = ""   # remapped → watsonx_space_id if set

    @property
    def effective_watsonx_base_url(self) -> str:
        """Return the active watsonx.ai base URL, respecting legacy env var."""
        return self.watsonx_base_url or self.orchestrate_base_url

    @property
    def effective_watsonx_space_id(self) -> str:
        """Return the active space ID, respecting legacy env var."""
        return self.watsonx_space_id or self.orchestrate_space_id

    @property
    def effective_watsonx_api_key(self) -> str:
        """Return the active API key (watsonx_api_key preferred, else orchestrate_api_key)."""
        return self.watsonx_api_key or self.orchestrate_api_key

    @property
    def orchestrate_active(self) -> bool:
        """True when a watsonx Orchestrate SaaS tenant URL is configured."""
        return bool(self.orchestrate_url and self.effective_watsonx_api_key)

    @property
    def watsonx_active(self) -> bool:
        """True when the watsonx.ai Chat API is usable (Path A)."""
        return bool(
            self.effective_watsonx_base_url
            and self.effective_watsonx_api_key
            and self.effective_watsonx_space_id
        )

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
