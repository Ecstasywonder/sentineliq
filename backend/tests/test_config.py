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


def test_orchestrate_prefers_dedicated_iam_key() -> None:
    settings = Settings(
        _env_file=None,
        app_env="development",
        orchestrate_api_key="orchestrate-key",
        watsonx_api_key="watsonx-key",
    )
    assert settings.effective_orchestrate_api_key == "orchestrate-key"


def test_orchestrate_api_version_is_restricted_to_documented_versions() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="development", orchestrate_api_version="v1")


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
