"""
Pytest configuration and shared fixtures for SentinelIQ backend tests.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings
from app.db.session import Base, get_db
from app.main import app
from app.models.user import User
from app.security.dependencies import AuthenticatedUser, get_current_user

settings = get_settings()

# ---------------------------------------------------------------------------
# Use an in-memory SQLite database for tests to avoid requiring PostgreSQL
# ---------------------------------------------------------------------------
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        yield session
        await session.rollback()


# ---------------------------------------------------------------------------
# Stub superuser — bypasses real JWT/DB auth for all route tests.
# Has every permission via platform_admin role.
# ---------------------------------------------------------------------------
_STUB_USER = User(
    id="test-user-001",
    email="test@sentineliq.test",
    full_name="Test User",
    hashed_password="$2b$12$unused",
    is_active=True,
    is_verified=True,
)
_STUB_AUTH = AuthenticatedUser(user=_STUB_USER, roles=["platform_admin"])


def _override_auth() -> AuthenticatedUser:
    return _STUB_AUTH


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Async test client with overridden DB session and stub auth."""

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = _override_auth
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
    app.dependency_overrides.clear()
