"""Provision a least-privilege service identity.

Example (run inside the backend runtime)::

    python -m app.security.provision_service_identity \
      --purpose orchestrate_tools

For integrations that cannot use OAuth client credentials, ``--token-file``
can still mint a one-time short-lived token. The token is never emitted to
stdout or application logs. The destination must not already exist and is
created with mode 0600.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, select

from app.db.session import AsyncSessionLocal
from app.models.audit import AuditEvent
from app.models.user import Role, User, UserRole
from app.security.passwords import hash_password
from app.security.rbac import SERVICE_PURPOSE_POLICIES
from app.security.tokens import create_service_access_token

DEFAULT_EMAILS = {
    "orchestrate_tools": "orchestrate-tools@service.sentineliq.internal",
    "event_ingestion": "event-ingestor@service.sentineliq.internal",
}


async def ensure_service_identity(purpose: str, email: str) -> str:
    """Converge on the single least-privilege identity for ``purpose``."""
    if purpose not in SERVICE_PURPOSE_POLICIES:
        raise ValueError(f"Unknown service purpose: {purpose}")
    role_name, _ = SERVICE_PURPOSE_POLICIES[purpose]

    async with AsyncSessionLocal() as session:
        role = await session.scalar(select(Role).where(Role.name == role_name))
        if role is None:
            role = Role(name=role_name, description=f"Service identity for {purpose}")
            session.add(role)
            await session.flush()

        user = await session.scalar(select(User).where(User.service_purpose == purpose))
        if user is not None and user.email != email.lower():
            raise ValueError(
                f"Purpose {purpose!r} is already assigned to a different service identity"
            )
        if user is None:
            user = await session.scalar(select(User).where(User.email == email.lower()))
        if user is None:
            user = User(
                email=email.lower(),
                full_name=f"SentinelIQ service: {purpose}",
                # No operator knows this random password; password login is also
                # rejected for every service-purpose identity.
                hashed_password=hash_password(secrets.token_urlsafe(48)),
                is_active=True,
                is_verified=True,
                service_purpose=purpose,
            )
            session.add(user)
            await session.flush()
        elif user.service_purpose != purpose:
            raise ValueError("Email already belongs to a different identity purpose")
        else:
            user.is_active = True

        # Re-provisioning converges on one role, removing accidental privilege
        # grants rather than carrying them into a new token.
        await session.execute(delete(UserRole).where(UserRole.user_id == user.id))
        session.add(
            UserRole(
                user_id=user.id,
                role_id=role.id,
                granted_by="system:service-provisioner",
            )
        )
        session.add(
            AuditEvent(
                action="service_identity_provisioned",
                actor="system:service-provisioner",
                actor_role="system",
                occurred_at=datetime.now(UTC).isoformat(),
                details_json=json.dumps(
                    {"target_user_id": user.id, "purpose": purpose, "role": role_name},
                    sort_keys=True,
                ),
            )
        )
        await session.commit()

        return user.id


async def provision_service_identity(purpose: str, email: str) -> tuple[str, str]:
    """Compatibility helper that provisions an identity and mints a token."""
    identity_id = await ensure_service_identity(purpose, email)
    role_name, _ = SERVICE_PURPOSE_POLICIES[purpose]
    return identity_id, create_service_access_token(identity_id, [role_name], purpose)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--purpose", choices=sorted(SERVICE_PURPOSE_POLICIES), required=True)
    parser.add_argument("--email", help="Dedicated service identity email")
    parser.add_argument(
        "--token-file",
        type=Path,
        help="Optional new mode-0600 file for a short-lived token (must not exist)",
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    email = args.email or DEFAULT_EMAILS[args.purpose]
    token_path: Path | None = args.token_file
    if token_path is None:
        identity_id = asyncio.run(ensure_service_identity(args.purpose, email))
        print(
            f"Provisioned {args.purpose} identity {identity_id}",
            file=sys.stderr,
        )
        return

    fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        identity_id, token = asyncio.run(provision_service_identity(args.purpose, email))
        os.write(fd, f"{token}\n".encode())
        os.fsync(fd)
    except BaseException:
        os.close(fd)
        token_path.unlink(missing_ok=True)
        raise
    else:
        os.close(fd)

    print(
        f"Provisioned {args.purpose} identity {identity_id}; token written to {token_path}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
