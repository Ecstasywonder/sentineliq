# Gate 6 -- RBAC & Authentication

**Date:** 2026-11-03
**Gate:** 6
**Status:** Complete
**Author:** IBM Bob (Principal Architect)

---

## 1. Scope

Gate 6 delivers the authentication and role-based access control layer. Every event endpoint is now guarded. Only authenticated callers with the correct permission can access each route.

---

## 2. Files Delivered

| File | Purpose |
|------|---------|
| `backend/app/security/passwords.py` | bcrypt password hash + verify |
| `backend/app/security/tokens.py` | JWT access + refresh token issuance and decoding |
| `backend/app/security/rbac.py` | Role -> permission mapping; `has_permission()` |
| `backend/app/security/dependencies.py` | `get_current_user` FastAPI dependency; `require_permission()` guard factory |
| `backend/app/schemas/auth.py` | `LoginRequest`, `TokenResponse`, `RefreshRequest`, `UserInfo` |
| `backend/app/api/v1/endpoints/auth.py` | `POST /token`, `POST /refresh`, `GET /me` |
| `backend/app/api/v1/router.py` | Updated -- auth router wired at `/api/v1/auth` |
| `backend/app/api/v1/endpoints/events.py` | Updated -- permission guards on all 4 routes |
| `backend/tests/conftest.py` | Updated -- stub auth override for existing tests |
| `backend/tests/test_auth.py` | 30 tests -- passwords, tokens, RBAC, endpoints |
| `docs/deployment.md` | Updated with Gate 6 run commands |

---

## 3. Auth Flow

```
POST /api/v1/auth/token
    │
    ├── Validate email + password against users table
    ├── Load role names from user_roles + roles tables
    ├── Issue access token  (HS256, contains sub + roles + exp)
    └── Issue refresh token (HS256, contains sub + exp only)

Subsequent requests:
    Authorization: Bearer <access_token>
    │
    └── get_current_user dependency
            ├── Decode + verify JWT
            ├── Load User from DB (checks is_active)
            ├── Load roles from DB
            └── Return AuthenticatedUser

POST /api/v1/auth/refresh
    │
    ├── Decode refresh token (must be type=refresh)
    ├── Load User (checks is_active)
    └── Issue new access + refresh tokens (rotation)
```

---

## 4. RBAC Permission Matrix

| Permission | officer | supervisor | response_team | facility_manager | security_admin | audit_reviewer | platform_admin | agent_admin |
|------------|:-------:|:----------:|:-------------:|:----------------:|:--------------:|:--------------:|:--------------:|:-----------:|
| `events:read` | Y | Y | Y | Y | Y | Y | Y | Y |
| `events:ingest` | | | | | Y | | Y | |
| `events:decide` | Y | Y | Y | | Y | | Y | |
| `events:escalate` | Y | Y | | | Y | | Y | |
| `events:override` | | Y | | | Y | | Y | |
| `audit:read` | | Y | | Y | Y | Y | Y | Y |
| `admin:users` | | | | | | | Y | |
| `admin:policy` | | | | | Y | | Y | |
| `admin:agents` | | | | | | | Y | Y |

---

## 5. Event Endpoint Guards

| Route | Permission Required |
|-------|-------------------|
| `POST /api/v1/events` | `events:ingest` |
| `GET /api/v1/events` | `events:read` |
| `GET /api/v1/events/{id}` | `events:read` |
| `PATCH /api/v1/events/{id}/status` | `events:decide` |

---

## 6. Test Strategy

Existing Gate 5 tests use the `client` fixture which now overrides `get_current_user` with a `platform_admin` stub — all permissions granted, no real DB auth needed. This keeps Gate 5 tests green without modifying them.

Auth-specific tests in `test_auth.py` clear `dependency_overrides` before each call to exercise the real auth path against the in-memory SQLite DB.

---

## 7. Acceptance Criteria -- Gate 6

- [x] Password hashing with bcrypt via passlib
- [x] JWT access tokens (HS256, 60 min lifetime)
- [x] JWT refresh tokens (HS256, 7 day lifetime)
- [x] Token type claim enforced (access != refresh)
- [x] Expired token rejected
- [x] `POST /api/v1/auth/token` implemented and tested
- [x] `POST /api/v1/auth/refresh` implemented and tested
- [x] `GET /api/v1/auth/me` implemented and tested
- [x] Login returns 401 for wrong password (no user enumeration)
- [x] Login returns 403 for disabled account
- [x] RBAC permission matrix defined for all 8 roles
- [x] `require_permission()` guard applied to all 4 events routes
- [x] Unauthenticated requests return 401
- [x] Insufficient-role requests return 403
- [x] Existing 113 Gate 5 tests remain green via stub auth override
- [x] `docs/deployment.md` updated

---

## 8. Next Gate

**Gate 7 -- Evidence Retrieval API (Context Tools)**

Will produce:
- Mock adapter implementations for access control, schedule, work orders, deliveries
- `GET /api/v1/tools/access-events` -- badge/access query tool
- `GET /api/v1/tools/schedule` -- schedule context tool
- `GET /api/v1/tools/work-orders` -- work order context tool
- `GET /api/v1/tools/delivery` -- delivery context tool
- `GET /api/v1/tools/location-policy` -- policy retrieval tool
- `GET /api/v1/tools/incident-history` -- incident search tool
- `GET /api/v1/tools/integration-health` -- health status tool
- Evidence aggregator service
- Integration tests for all tools
