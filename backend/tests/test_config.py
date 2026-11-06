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
    return Settings(**values)


def test_production_accepts_explicit_safe_configuration() -> None:
    settings = _production_settings()
    assert settings.app_env == "production"


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"debug": True}, "DEBUG"),
        ({"secret_key": "CHANGE_ME_INSECURE_DEFAULT"}, "SECRET_KEY"),
        ({"database_url": "postgresql+asyncpg://sentineliq:changeme@db/sentineliq"}, "DATABASE_URL"),
        ({"cors_origins": ["*"]}, "CORS_ORIGINS"),
        ({"cors_origins": ["http://localhost:3000"]}, "localhost"),
    ],
)
def test_production_rejects_insecure_defaults(overrides: dict[str, object], expected: str) -> None:
    with pytest.raises(ValidationError, match=expected):
        _production_settings(**overrides)


def test_development_allows_local_defaults() -> None:
    settings = Settings(app_env="development")
    assert settings.debug is False
