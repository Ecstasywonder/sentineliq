"""Security invariants for optional interactive seed accounts."""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.seed import _load_interactive_seed_accounts, _seed_interactive_accounts
from app.db.session import Base
from app.models import Role, User


@pytest_asyncio.fixture
async def isolated_seed_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


def _operator_environment(*, password: str) -> dict[str, str]:
    return {
        "SEED_INTERACTIVE_OPERATOR_ENABLED": "true",
        "SEED_INTERACTIVE_OPERATOR_EMAIL": "seed-operator@example.test",
        "SEED_INTERACTIVE_OPERATOR_PASSWORD": password,
    }


def test_interactive_accounts_are_disabled_by_default() -> None:
    assert _load_interactive_seed_accounts({}) == ()


@pytest.mark.parametrize(
    ("environment", "expected_setting"),
    [
        (
            {"SEED_INTERACTIVE_OPERATOR_EMAIL": "seed-operator@example.test"},
            "SEED_INTERACTIVE_OPERATOR_ENABLED",
        ),
        (
            {"SEED_INTERACTIVE_OPERATOR_ENABLED": "true"},
            "SEED_INTERACTIVE_OPERATOR_EMAIL",
        ),
        (
            {
                "SEED_INTERACTIVE_OPERATOR_ENABLED": "true",
                "SEED_INTERACTIVE_OPERATOR_EMAIL": "seed-operator@example.test",
            },
            "SEED_INTERACTIVE_OPERATOR_PASSWORD",
        ),
    ],
)
def test_partial_interactive_account_configuration_is_rejected(
    environment: dict[str, str], expected_setting: str
) -> None:
    with pytest.raises(RuntimeError, match=expected_setting):
        _load_interactive_seed_accounts(environment)


@pytest.mark.asyncio
async def test_default_seed_creates_no_interactive_accounts(
    isolated_seed_session: AsyncSession,
) -> None:
    await _seed_interactive_accounts(isolated_seed_session, environ={})

    assert list(await isolated_seed_session.scalars(select(User))) == []


@pytest.mark.asyncio
async def test_opt_in_seed_is_idempotent_and_never_reactivates_existing_user(
    isolated_seed_session: AsyncSession,
) -> None:
    isolated_seed_session.add(Role(name="officer", description="Officer"))
    await isolated_seed_session.commit()
    environment = _operator_environment(password=secrets.token_urlsafe(24))

    await _seed_interactive_accounts(isolated_seed_session, environ=environment)
    user = await isolated_seed_session.scalar(
        select(User).where(User.email == environment["SEED_INTERACTIVE_OPERATOR_EMAIL"])
    )
    assert user is not None
    assert user.is_active is True
    original_password_hash = user.hashed_password

    user.is_active = False
    await isolated_seed_session.commit()
    await _seed_interactive_accounts(
        isolated_seed_session,
        environ=_operator_environment(password=secrets.token_urlsafe(24)),
    )

    users = list(await isolated_seed_session.scalars(select(User)))
    assert len(users) == 1
    assert users[0].is_active is False
    assert users[0].hashed_password == original_password_hash
