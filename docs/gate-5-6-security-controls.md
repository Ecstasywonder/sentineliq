# Gate 5-6 security controls

## Refresh-token lifecycle

Login creates a refresh-token family and persists only the SHA-256 hash, token
ID, family ID, user ID, and expiry in `refresh_tokens`. Each refresh is a
one-time atomic rotation under a database row lock. Reuse of a consumed,
revoked, or expired token revokes the entire family, including descendants.
A logout request is non-enumerating and idempotently revokes the presented
token's entire family before the browser clears its local session.
A signed JWT without a matching database record is invalid.

Apply `alembic upgrade head` on EC2 before starting the updated API (the current
head is `0004_decision_snapshot`). Existing stateless refresh tokens
intentionally become invalid; users must log in again after deployment.

## Rate and body limits

When `ENABLE_RATE_LIMITING=true`, the API enforces three sliding-window scopes:

- all `/api/v1` requests: `RATE_LIMIT_API_PER_MINUTE` per peer/authenticated principal;
- event ingestion: `RATE_LIMIT_EVENTS_PER_MINUTE` in addition to the API limit;
- login, refresh, and logout: `RATE_LIMIT_AUTH_PER_MINUTE` per direct peer in addition
  to the API limit; optional bearer headers cannot select another auth bucket.

Rejected requests return `429`, `Retry-After`, and structured error code
`RATE_LIMITED`. Request bodies above `MAX_REQUEST_BODY_BYTES` return `413`
before endpoint validation.

The included limiter protects the current single-process EC2 deployment. If
the API is scaled to multiple workers or hosts, enforce the same limits at the
load balancer/API gateway or replace the process-local store with a shared
atomic backend. Do not trust forwarded client-IP headers without configuring a
known proxy boundary.

## Ingestion metadata privacy

`raw_metadata` is recursively bounded by encoded bytes, depth, key count, list
items, and individual string size. Non-finite or non-JSON values are rejected.
Secret and direct-identifier fields (tokens, credentials, passwords, email,
phone, national IDs, biometrics, and cookies) are replaced with
`[REDACTED]` before persistence. Integrations should still send the minimum
metadata required for assessment and use first-class event fields where one is
available.

## EC2 validation

From the checked-out project on EC2, install and test only in that environment:

```bash
cd backend
alembic upgrade head
pytest tests/test_auth.py tests/test_security_controls.py tests/test_events_api.py
ruff check app tests
```
