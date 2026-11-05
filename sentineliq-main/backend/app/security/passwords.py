"""
Password hashing utilities -- Gate 6.

Uses bcrypt directly (not passlib) for Python 3.14 compatibility.
passlib's bcrypt backend is incompatible with bcrypt>=4.0 on Python 3.14.
"""

from __future__ import annotations

import bcrypt


def hash_password(plain: str) -> str:
    """Return a bcrypt hash of *plain*."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if *plain* matches *hashed*."""
    return bcrypt.checkpw(plain.encode(), hashed.encode())
