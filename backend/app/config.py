"""
Application configuration — loaded from environment variables.
All settings have explicit types and defaults.
Secrets are NEVER committed — use .env file (see .env.example).
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
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
    app_env: Literal["development", "staging", "production", "test"] = "development"
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
    orchestrate_api_version: Literal["v2", "v1_5"] = "v2"
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
    # Embedding model used by Gate 8 hybrid retrieval when watsonx.ai is active.
    watsonx_embedding_model_id: str = "ibm/slate-30m-english-rtrvr"
    watsonx_api_version: str = "2024-05-31"

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
    orchestrate_base_url: str = ""  # remapped → watsonx_base_url if set
    orchestrate_space_id: str = ""  # remapped → watsonx_space_id if set

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
    def effective_orchestrate_api_key(self) -> str:
        """Return the Orchestrate IAM key, preferring its dedicated setting."""
        return self.orchestrate_api_key or self.watsonx_api_key

    @property
    def orchestrate_active(self) -> bool:
        """True when a watsonx Orchestrate SaaS tenant URL is configured."""
        if self.app_env == "test" or "PYTEST_CURRENT_TEST" in os.environ:
            return False
        return bool(self.orchestrate_url and self.effective_orchestrate_api_key)

    @property
    def watsonx_active(self) -> bool:
        """True when the watsonx.ai Chat API is usable (Path A)."""
        if self.app_env == "test" or "PYTEST_CURRENT_TEST" in os.environ:
            return False
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
    rate_limit_events_per_minute: int = Field(default=100, ge=1, le=100_000)
    rate_limit_api_per_minute: int = Field(default=300, ge=1, le=100_000)
    rate_limit_auth_per_minute: int = Field(default=20, ge=1, le=10_000)

    # Request/metadata resource and privacy boundaries.  These are enforced
    # before arbitrary integration payloads are persisted.
    max_request_body_bytes: int = Field(default=1_048_576, ge=1_024, le=10_485_760)
    event_raw_metadata_max_bytes: int = Field(default=16_384, ge=256, le=262_144)
    event_raw_metadata_max_depth: int = Field(default=5, ge=1, le=16)
    event_raw_metadata_max_keys: int = Field(default=64, ge=1, le=1_024)
    event_raw_metadata_max_items: int = Field(default=100, ge=1, le=10_000)
    event_raw_metadata_max_string_bytes: int = Field(default=2_048, ge=1, le=65_536)

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

    @model_validator(mode="after")
    def reject_insecure_production_configuration(self) -> Settings:
        """Prevent the application from starting with known unsafe production defaults.

        Development intentionally remains frictionless, but a production process
        must receive explicitly managed credentials and an explicit browser
        allow-list.  Failing during settings construction keeps an unhealthy
        deployment from appearing ready.
        """
        if self.app_env != "production":
            return self

        errors: list[str] = []
        insecure_secret_values = {
            "",
            "CHANGE_ME_INSECURE_DEFAULT",
            "CHANGE_ME_GENERATE_WITH_SECRETS_TOKEN_HEX_32",
            "ci-test-secret-key-not-for-production",
        }
        if self.debug:
            errors.append("DEBUG must be false in production")
        if self.secret_key in insecure_secret_values or len(self.secret_key) < 32:
            errors.append("SECRET_KEY must be a non-default value of at least 32 characters")
        if "changeme" in self.database_url.lower() or "changeme" in self.database_url_sync.lower():
            errors.append("DATABASE_URL and DATABASE_URL_SYNC must not use placeholder credentials")
        if not self.cors_origins or "*" in self.cors_origins:
            errors.append("CORS_ORIGINS must be an explicit, non-wildcard allow-list")
        if any(origin.startswith("http://localhost") for origin in self.cors_origins):
            errors.append("CORS_ORIGINS must not include localhost in production")

        if errors:
            raise ValueError("Invalid production configuration: " + "; ".join(errors))
        return self


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings singleton."""
    return Settings()
