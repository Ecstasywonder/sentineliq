"""
Password hashing utilities -- Gate 6.

Uses bcrypt directly (not passlib) for Python 3.14 compatibility.
passlib's bcrypt backend is incompatible with bcrypt>=4.0 on Python 3.14.
"""

from __future__ import annotations

import bcrypt

# Generated once per process so an unknown account still pays the same bcrypt
# verification cost as a known one. The value is never used as a credential.
_DUMMY_PASSWORD_HASH = bcrypt.hashpw(
    b"sentineliq-nonexistent-account",
    bcrypt.gensalt(),
).decode()


def hash_password(plain: str) -> str:
    """Return a bcrypt hash of *plain*."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if *plain* matches *hashed*."""
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def verify_password_or_dummy(plain: str, hashed: str | None) -> bool:
    """Always perform bcrypt work and return false for an unknown account."""
    matches = verify_password(plain, hashed or _DUMMY_PASSWORD_HASH)
    return hashed is not None and matches
