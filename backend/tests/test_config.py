"""Configuration safety tests for development and production startup."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


def _production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "production",
        "debug": False,
        "secret_key": "a-production-secret-that-is-longer-than-thirty-two-characters",
        "database_url": "postgresql+asyncpg://user:strong-password@db:5432/sentineliq",
        "database_url_sync": "postgresql://user:strong-password@db:5432/sentineliq",
        "cors_origins": ["https://console.example.com"],
        "enable_simulator_api": False,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_production_accepts_explicit_safe_configuration() -> None:
    settings = _production_settings()
    assert settings.app_env == "production"


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"debug": True}, "DEBUG"),
        ({"secret_key": "CHANGE_ME_INSECURE_DEFAULT"}, "SECRET_KEY"),
        (
            {"database_url": "postgresql+asyncpg://sentineliq:changeme@db/sentineliq"},
            "DATABASE_URL",
        ),
        ({"cors_origins": ["*"]}, "CORS_ORIGINS"),
        ({"cors_origins": ["http://localhost:3000"]}, "localhost"),
    ],
)
def test_production_rejects_insecure_defaults(overrides: dict[str, object], expected: str) -> None:
    with pytest.raises(ValidationError, match=expected):
        _production_settings(**overrides)


def test_development_allows_local_defaults() -> None:
    settings = Settings(_env_file=None, app_env="development")
    assert settings.debug is False


def test_production_rejects_simulator_api() -> None:
    with pytest.raises(ValidationError, match="ENABLE_SIMULATOR_API"):
        _production_settings(enable_simulator_api=True)


def test_orchestrate_prefers_dedicated_iam_key() -> None:
    settings = Settings(
        _env_file=None,
        app_env="development",
        orchestrate_api_key="orchestrate-key",
        watsonx_api_key="watsonx-key",
    )
    assert settings.effective_orchestrate_api_key == "orchestrate-key"


def test_orchestrate_api_version_rejects_legacy_contract() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="development", orchestrate_api_version="v2")


def test_orchestrate_defaults_to_live_verified_v1_contract() -> None:
    settings = Settings(_env_file=None, app_env="development")
    assert settings.orchestrate_api_version == "v1"


def test_orchestrate_active_requires_deployed_agent_uuids() -> None:
    with pytest.raises(ValidationError, match="deployed agent UUIDs are required"):
        Settings(
            _env_file=None,
            app_env="development",
            orchestrate_url=(
                "https://us-south.watson-orchestrate.cloud.ibm.com/instances/instance-123"
            ),
            orchestrate_api_key="secret",
            orchestrate_triage_agent_id="sentinel_triage_agent",
            orchestrate_context_agent_id="sentinel_context_agent",
            orchestrate_explanation_agent_id="sentinel_explanation_agent",
            orchestrate_coordinator_agent_id="sentinel_coordinator",
        )


def test_orchestrate_configuration_accepts_environment_agent_uuids() -> None:
    settings = Settings(
        _env_file=None,
        app_env="development",
        orchestrate_url=(
            "https://us-south.watson-orchestrate.cloud.ibm.com/instances/instance-123"
        ),
        orchestrate_api_key="secret",
        orchestrate_triage_agent_id="11111111-1111-4111-8111-111111111111",
        orchestrate_context_agent_id="22222222-2222-4222-8222-222222222222",
        orchestrate_explanation_agent_id="33333333-3333-4333-8333-333333333333",
        orchestrate_coordinator_agent_id="44444444-4444-4444-8444-444444444444",
    )
    assert settings.orchestrate_triage_agent_id == "11111111-1111-4111-8111-111111111111"


def test_orchestrate_tools_oauth_credentials_are_atomic_and_redacted() -> None:
    secret = "service-client-secret-longer-than-thirty-two-characters"
    settings = Settings(
        _env_file=None,
        app_env="development",
        orchestrate_tools_client_id="sentineliq-tools",
        orchestrate_tools_client_secret=secret,
    )
    assert settings.orchestrate_tools_oauth_configured is True
    assert secret not in repr(settings)

    with pytest.raises(ValidationError, match="must be configured together"):
        Settings(
            _env_file=None,
            app_env="development",
            orchestrate_tools_client_id="sentineliq-tools",
        )


def test_production_orchestrate_requires_tools_oauth_credentials() -> None:
    agent_ids = {
        "orchestrate_triage_agent_id": "11111111-1111-4111-8111-111111111111",
        "orchestrate_context_agent_id": "22222222-2222-4222-8222-222222222222",
        "orchestrate_explanation_agent_id": "33333333-3333-4333-8333-333333333333",
        "orchestrate_coordinator_agent_id": "44444444-4444-4444-8444-444444444444",
    }
    with pytest.raises(ValidationError, match="ORCHESTRATE_TOOLS_CLIENT"):
        _production_settings(
            orchestrate_url=(
                "https://us-south.watson-orchestrate.cloud.ibm.com/instances/instance-123"
            ),
            orchestrate_api_key="secret",
            **agent_ids,
        )

    settings = _production_settings(
        orchestrate_url=(
            "https://us-south.watson-orchestrate.cloud.ibm.com/instances/instance-123"
        ),
        orchestrate_api_key="secret",
        orchestrate_tools_client_id="sentineliq-tools",
        orchestrate_tools_client_secret=(
            "service-client-secret-longer-than-thirty-two-characters"
        ),
        **agent_ids,
    )
    assert settings.orchestrate_tools_oauth_configured is True


def test_watsonx_base_url_prefers_primary_setting() -> None:
    settings = Settings(
        _env_file=None,
        app_env="development",
        watsonx_base_url="https://eu-de.ml.cloud.ibm.com",
        orchestrate_base_url="https://us-south.ml.cloud.ibm.com",
    )
    assert settings.effective_watsonx_base_url == "https://eu-de.ml.cloud.ibm.com"


def test_watsonx_base_url_preserves_legacy_fallback() -> None:
    settings = Settings(
        _env_file=None,
        app_env="development",
        watsonx_base_url="",
        orchestrate_base_url="https://us-south.ml.cloud.ibm.com",
    )
    assert settings.effective_watsonx_base_url == "https://us-south.ml.cloud.ibm.com"
