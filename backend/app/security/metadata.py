"""Validation and privacy controls for untrusted integration metadata."""

from __future__ import annotations

import json
import math
import re
from typing import Any

_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "biometric",
    "biometric_template",
    "cookie",
    "credential",
    "email",
    "face_embedding",
    "national_id",
    "password",
    "passwd",
    "phone",
    "refresh_token",
    "secret",
    "session_id",
    "set_cookie",
    "ssn",
    "token",
}
_NORMALISE_KEY = re.compile(r"[^a-z0-9]+")
_CAMEL_CASE_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
REDACTED = "[REDACTED]"


def _normalised_key(key: str) -> str:
    snake_case = _CAMEL_CASE_BOUNDARY.sub("_", key.strip())
    return _NORMALISE_KEY.sub("_", snake_case.lower()).strip("_")


def _is_sensitive_key(key: str) -> bool:
    normalised = _normalised_key(key)
    if normalised in _SENSITIVE_KEYS:
        return True
    parts = set(normalised.split("_"))
    return bool(
        parts
        & {
            "apikey",
            "authorization",
            "biometric",
            "cookie",
            "credential",
            "email",
            "password",
            "passwd",
            "phone",
            "secret",
            "session",
            "ssn",
            "token",
        }
    )


def sanitize_metadata(
    value: dict[str, Any],
    *,
    max_bytes: int,
    max_depth: int,
    max_keys: int,
    max_items: int,
    max_string_bytes: int,
) -> dict[str, Any]:
    """Return bounded JSON metadata with secret/PII fields redacted.

    Limits apply recursively and are checked before the value reaches an ORM
    model.  Unsupported/non-finite values are rejected instead of being stored
    as non-standard JSON.
    """
    counters = {"keys": 0, "items": 0}

    def walk(item: Any, depth: int) -> Any:
        if depth > max_depth:
            raise ValueError(f"raw_metadata exceeds maximum depth {max_depth}")

        if isinstance(item, dict):
            output: dict[str, Any] = {}
            for key, nested in item.items():
                if not isinstance(key, str):
                    raise ValueError("raw_metadata object keys must be strings")
                if not key or len(key.encode("utf-8")) > 128:
                    raise ValueError("raw_metadata keys must be 1-128 UTF-8 bytes")
                counters["keys"] += 1
                if counters["keys"] > max_keys:
                    raise ValueError(f"raw_metadata exceeds maximum key count {max_keys}")
                output[key] = REDACTED if _is_sensitive_key(key) else walk(nested, depth + 1)
            return output

        if isinstance(item, list):
            counters["items"] += len(item)
            if counters["items"] > max_items:
                raise ValueError(f"raw_metadata exceeds maximum item count {max_items}")
            return [walk(nested, depth + 1) for nested in item]

        if isinstance(item, str):
            if len(item.encode("utf-8")) > max_string_bytes:
                raise ValueError(
                    f"raw_metadata string exceeds maximum size {max_string_bytes} bytes"
                )
            return item

        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError("raw_metadata numbers must be finite")
        if item is None or isinstance(item, (bool, int, float)):
            return item
        raise ValueError(f"raw_metadata contains unsupported value type {type(item).__name__}")

    sanitized = walk(value, 0)
    encoded = json.dumps(
        sanitized,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > max_bytes:
        raise ValueError(f"raw_metadata exceeds maximum encoded size {max_bytes} bytes")
    return sanitized
