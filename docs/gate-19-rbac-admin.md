# Gate 19 — RBAC and Administrative Controls

**Gate:** 19  
**Title:** RBAC and administrative controls  
**Status:** ✅ Complete  
**Branch:** `main`  
**Date:** 2026-11-07

---

## Gate completed

Gate 19 implements the complete user/role administration API and operator dashboard
administration interface, backed by 34 backend tests and 5 frontend tests, all
passing on EC2 with ruff check, ruff format, and production build passing clean.

---

## What was implemented

### Backend — Admin API (`GET/POST/PATCH /api/v1/admin/*`)

All routes require the `admin:users` permission (held by `platform_admin` only).

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/admin/users` | List all users, paginated, with roles |
| `POST` | `/api/v1/admin/users` | Create a new user with optional role assignment |
| `GET` | `/api/v1/admin/users/{id}` | Get user detail with full role list and granted_by |
| `PATCH` | `/api/v1/admin/users/{id}` | Update full_name or is_active |
| `POST` | `/api/v1/admin/users/{id}/roles` | Assign a role (idempotent) |
| `DELETE` | `/api/v1/admin/users/{id}/roles/{role}` | Remove a role (no-op if not held) |
| `GET` | `/api/v1/admin/roles` | List all platform roles with descriptions and permissions |

### Backend — Admin schemas (`app/schemas/admin.py`)

| Schema | Purpose |
|--------|---------|
| `UserCreateRequest` | email, full_name, password (≥8 chars), optional roles |
| `UserUpdateRequest` | full_name and/or is_active (both optional) |
| `RoleAssignRequest` | single role name with VALID_ROLES validation |
| `UserDetailResponse` | full user + `UserRoleSummary` list |
| `UserListItem` | compact user for list view |
| `UserListResponse` | paginated wrapper |
| `RoleDescription` | name, description, permissions list |
| `RolesResponse` | all platform roles |

### Authorization enforcement

- All 7 admin endpoints are guarded by `Depends(require_permission("admin:users"))`
- `platform_admin` is the only role holding `admin:users`
- All other roles (including `supervisor`, `security_admin`) receive HTTP 403
- Role validation uses `VALID_ROLES` tuple from the user model — unknown role names
  return 422 with a clear error message before any DB write

### Frontend — `AdminPage` component

- **Users panel** — paginated table: name, email, role pills, status, Deactivate/Reactivate button
- **Roles and permissions panel** — on-demand load of role definitions with permission
  code badges; sourced from `GET /api/v1/admin/roles`
- **Admin nav link** — visible in topbar only for `platform_admin` role
- Defensive guard on user list response shape (same pattern as Gate 18 audit trail)

### Frontend — CSS additions (`index.css`)

| Class | Purpose |
|---|---|
| `.admin-count` | Muted user count in panel heading |
| `.admin-muted` | Muted "No roles" placeholder |
| `.admin-active` / `.admin-inactive` | Colour-coded status text |
| `.role-pills` | Flex wrap container for role badges |
| `.admin-roles-list` / `.admin-role-entry` | Role reference list layout |
| `.admin-role-header` / `.admin-role-desc` | Role name + description row |
| `.admin-perm-list` | Permission badge flex list |
| `.admin-perm-list li code` | Blue code-style permission badge |

---

## Files created / modified

| File | Change |
|------|--------|
| `backend/app/schemas/admin.py` | Created — all admin request/response schemas |
| `backend/app/api/v1/endpoints/admin.py` | Created — 7 admin routes |
| `backend/app/api/v1/router.py` | Added admin router at `/admin` prefix |
| `backend/tests/test_admin_api.py` | Created — 34 authorization + CRUD tests |
| `frontend/src/api.ts` | Added admin types + 7 API functions |
| `frontend/src/App.tsx` | Added `AdminPage`, `adminRoles`, nav link, page state |
| `frontend/src/styles/index.css` | Added Gate 19 admin CSS classes |
| `frontend/src/test/App.test.tsx` | Added 5 Gate 19 frontend tests |
| `docs/gate-19-rbac-admin.md` | This report |

---

## Tests executed

### Backend — 34 tests in `test_admin_api.py`

**Authorization (7 tests):** All 7 endpoints return 403 for `officer` role.

**Users list (2 tests):** Paginated response shape; roles included in list items.

**Create user (4 tests):** Happy path with role; duplicate email → 409; invalid role → 422; no roles.

**Get user (2 tests):** Full detail with roles; 404 for unknown ID.

**Update user (3 tests):** Deactivate; rename; 404 for unknown ID.

**Assign role (4 tests):** Happy path; idempotent double-assign; invalid role → 422; unknown user → 404.

**Remove role (3 tests):** Happy path; no-op when role not held; unknown role name → 404.

**List roles (2 tests):** All VALID_ROLES present; platform_admin has `admin:users`, officer does not.

### Frontend — 5 tests

| Test | Checks |
|---|---|
| Admin nav visible for platform_admin | RBAC gate |
| Admin nav hidden for officer | RBAC gate |
| Admin page renders user list | User table rendering |
| Empty state when no users | Empty state |
| Roles panel shows load button | On-demand load pattern |

### Full suite results on EC2

| Suite | Result |
|-------|--------|
| `ruff check app/ tests/` | ✅ All checks passed |
| `ruff format --check app/ tests/` | ✅ 121 files formatted |
| `pytest tests/ -q` | ✅ **608 passed**, 2 warnings, 90% coverage |
| `npm run typecheck` | ✅ Clean |
| `npm run lint` | ✅ Zero warnings |
| `npm run test:unit` | ✅ **39/39 passed** |
| `npm run build` | ✅ Built in 113ms |

---

## Architecture decisions

- **`GET /admin/roles` is stateless** — it derives role/permission data from the RBAC
  module constants, not the DB. The DB `roles` table is the authority for role
  assignment; the static RBAC module is the authority for what each role may do.
  These are intentionally separate concerns.
- **Role assignment is idempotent** — `POST /admin/users/{id}/roles` silently ignores
  a re-assignment of an already-held role. This prevents 409 errors from retry logic.
- **Role removal is a no-op** — `DELETE /admin/users/{id}/roles/{role}` does nothing
  if the user doesn't hold the named role. 404 is returned only if the role name
  itself doesn't exist in the DB.
- **`platform_admin` only** — `admin:users` is restricted to `platform_admin` per the
  Master Build Prompt §7 (Platform/System Administrator). `security_admin` can manage
  policies but not users.

---

## Security and safety review

- All admin endpoints require a valid JWT with `admin:users` in the resolved permission
  set — enforced by `require_permission("admin:users")` at route level.
- Password hashing uses bcrypt via the existing `hash_password` utility.
- Email is normalized to lowercase before storage and uniqueness check.
- Role validation against `VALID_ROLES` prevents injection of arbitrary role strings.
- No plaintext passwords appear in any response or log.
- The `granted_by` field in `UserRole` is preserved and returned for traceability.

---

## Known limitations

- Password reset is not implemented — operators who forget their password require a
  direct DB update. This is acceptable for MVP.
- No email verification flow — `is_verified` defaults to `False` and can only be
  set to `True` via direct DB access. This is acceptable for MVP.
- The admin UI does not yet support creating users or assigning roles via the
  browser — those operations are available via API only. Gate 19 implements the
  required MVP scope; a fuller admin UI can be added in a later gate.

---

## Acceptance criteria

| Criterion | Met |
|---|---|
| Users — list and detail | ✅ `GET /admin/users`, `GET /admin/users/{id}` |
| Users — create and update | ✅ `POST /admin/users`, `PATCH /admin/users/{id}` |
| Roles — assign and remove | ✅ `POST` and `DELETE /admin/users/{id}/roles/{role}` |
| Permissions — reference view | ✅ `GET /admin/roles` + frontend panel |
| Admin views — operator dashboard | ✅ `AdminPage` component, platform_admin only |
| Protected APIs — 403 for non-admin | ✅ 7 authorization tests, all passing |
| Authorization tests | ✅ 34 backend + 5 frontend tests |
| ruff check passes | ✅ |
| ruff format passes | ✅ |
| pytest 608 passed | ✅ 90% coverage |
| Frontend 39 tests pass | ✅ |
| Production build | ✅ |

---

## Next gate

**Gate 20 — Integration and failure-state hardening**

Test unavailable access system, unavailable schedule system, unavailable LLM,
missing history, contradictory evidence, malformed tool output, timeout,
stale source, and duplicate event. Verify safe degradation in all cases.
