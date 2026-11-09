# Gate 25 — MVP Demonstration and Freeze

**Document ID:** SNTL-DEMO-001  
**Version:** 1.0  
**Date:** 2026-11-08  
**Status:** Ready for demonstration  
**Author:** IBM Bob (Principal Architect)

> **STOP — Gate 25 scope freeze.**  
> After a successful demonstration the MVP scope is frozen.  
> Do not begin production expansion (Gate 26+) until the operator explicitly approves this gate.

---

## 1. Port forwarding — accessing the platform from your browser

All SentinelIQ services bind to the EC2 **loopback address** (`127.0.0.1`) only.
Nothing is publicly exposed on the EC2 instance's internet-facing IP.
To reach the platform from your local machine you must open an SSH tunnel.

### What you need

| Item | Value |
|------|-------|
| EC2 host | `ec2-54-164-137-222.compute-1.amazonaws.com` |
| SSH user | `ubuntu` |
| Key file | `sentinelIq.pem` (in your local project folder or known path) |
| Local port | `3000` (frontend) — any free port on your machine works |
| Remote port | `3000` (EC2 loopback, mapped from container port `8080`) |

### Tunnel command — copy and run in Git Bash or any terminal

```bash
ssh -i "sentinelIq.pem" \
    -L 3000:127.0.0.1:3000 \
    -N -f \
    ubuntu@ec2-54-164-137-222.compute-1.amazonaws.com
```

| Flag | Meaning |
|------|---------|
| `-L 3000:127.0.0.1:3000` | Forward your local port 3000 → EC2 port 3000 |
| `-N` | No remote command — tunnel only |
| `-f` | Background the process after authenticating |

Once the tunnel is open, open your browser to:

```
http://localhost:3000
```

The SentinelIQ login screen appears.

### Stop the tunnel when you're done

```bash
# Find the SSH tunnel process
ps aux | grep "sentinelIq.pem"

# Kill it by PID (replace <PID> with the number shown)
kill <PID>
```

### If you also need direct API access (optional)

The backend API is on EC2 port `8000`. Forward it the same way if you want to
run `curl` commands or hit the Swagger UI (`/docs`) locally:

```bash
ssh -i "sentinelIq.pem" \
    -L 3000:127.0.0.1:3000 \
    -L 8000:127.0.0.1:8000 \
    -N -f \
    ubuntu@ec2-54-164-137-222.compute-1.amazonaws.com
```

Swagger UI: `http://localhost:8000/docs`  
API base: `http://localhost:8000/api/v1`

### How the routing works once the tunnel is open

```
Your browser
    │
    │  http://localhost:3000/              (React SPA)
    │  http://localhost:3000/api/v1/...   (API calls, same origin)
    ▼
SSH tunnel (localhost:3000 → EC2 127.0.0.1:3000)
    ▼
EC2 Docker bridge: frontend container nginx :8080
    │
    ├─ Static files  →  /usr/share/nginx/html  (React bundle)
    │
    └─ /api/*        →  proxy_pass http://backend:8000
                            ▼
                        Backend FastAPI container :8000
                            ▼
                        PostgreSQL container :5432
```

No `/api/` calls cross the tunnel separately — nginx resolves them over the
private Docker bridge network. The browser only needs the one tunnel.

---

## 2. EC2 pre-flight (run on EC2 before opening the tunnel)

SSH into EC2 in a separate terminal first and verify all services are up:

```bash
ssh -i "sentinelIq.pem" ubuntu@ec2-54-164-137-222.compute-1.amazonaws.com
```

### 2a. Pull latest code and start services

```bash
cd ~/sentineliq

# Pull Gates 22-24 if not already on main
git pull origin main

# Build and start all containers (first run takes ~2-3 min)
POSTGRES_PASSWORD=<your-db-password> \
docker compose -f infra/docker/docker-compose.yml up -d --build

# Check all three containers are running
docker compose -f infra/docker/docker-compose.yml ps
```

Expected output:
```
NAME                    STATUS         PORTS
sentineliq-postgres     Up (healthy)   127.0.0.1:5432->5432/tcp
sentineliq-backend      Up (healthy)   127.0.0.1:8000->8000/tcp
sentineliq-frontend     Up             127.0.0.1:3000->8080/tcp
```

### 2b. Run migrations

```bash
docker compose -f infra/docker/docker-compose.yml exec backend \
  alembic upgrade head
```

Expected last line: `Running upgrade ... -> 0005_security_audit`

### 2c. Seed the database

```bash
docker compose -f infra/docker/docker-compose.yml exec backend \
  python -m app.db.seed
```

Expected: log lines for `seed.roles_done`, `seed.facility_done`,
`seed.risk_policy_done`, `seed.complete`.

### 2d. Create a demo operator account

```bash
docker compose -f infra/docker/docker-compose.yml exec backend python3 - <<'PY'
import asyncio, uuid
from app.db.session import AsyncSessionLocal
from app.models.user import User, Role, UserRole
from app.security.passwords import hash_password
from sqlalchemy import select

async def create_demo_user():
    async with AsyncSessionLocal() as session:
        # Use an existing role
        role = await session.scalar(select(Role).where(Role.name == "platform_admin"))
        if role is None:
            raise RuntimeError("Roles not seeded — run seed first")
        email = "demo@sentineliq.dev"
        existing = await session.scalar(select(User).where(User.email == email))
        if existing:
            print(f"User {email} already exists (id={existing.id})")
            return
        user = User(
            id=str(uuid.uuid4()),
            email=email,
            full_name="Demo Operator",
            hashed_password=hash_password("SentinelIQ-Demo-2026"),
            is_active=True,
            is_verified=True,
        )
        session.add(user)
        await session.flush()
        session.add(UserRole(id=str(uuid.uuid4()), user_id=user.id, role_id=role.id))
        await session.commit()
        print(f"Created demo operator: {email} / SentinelIQ-Demo-2026")

asyncio.run(create_demo_user())
PY
```

### 2e. Verify health

```bash
curl -s http://localhost:8000/health | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['status'])"
# Expected: ok

curl -s http://localhost:8000/ready | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['status'])"
# Expected: ready
```

---

## 3. Demonstration flow

Open `http://localhost:3000` in your browser (tunnel must be active).

Walk through each step of the Gate 25 required flow:

```
Simulated event
→ SentinelIQ ingestion
→ watsonx Orchestrate workflow (or deterministic fallback)
→ evidence retrieval
→ deterministic risk score
→ confidence
→ evidence-backed explanation
→ operator dashboard
→ human decision
→ audit record
```

### Step 1 — Authenticate

1. Browser opens to `http://localhost:3000` → sign-in screen appears.
2. Enter credentials: `demo@sentineliq.dev` / `SentinelIQ-Demo-2026`
3. Dashboard loads showing the event queue.

**Checkpoint:** Operator name displayed. Event queue visible (may be empty before seeding).

### Step 2 — Seed a simulated event (Scenario B — high-risk unverified access)

In the EC2 terminal:

```bash
# Seed demo scenario B (unverified after-hours, high-risk) via the API
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/token \
  -H "Content-Type: application/json" \
  -d '{"email":"demo@sentineliq.dev","password":"SentinelIQ-Demo-2026"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -s -X POST http://localhost:8000/api/v1/simulator/events \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"scenario_ids":["demo-scenario-b"]}' \
  | python3 -m json.tool
```

**Checkpoint:** Response shows the event ID and status `normalised`.

### Step 3 — Event appears in queue

Refresh the browser dashboard. The new event appears in the queue with:
- Event type: `person detected`
- Location: `LOADING_DOCK_3`
- Status: `normalised` (awaiting assessment)
- Risk: Not yet assessed

### Step 4 — Run assessment (SentinelIQ ingestion → agent workflow → risk + confidence)

Click the event to open its detail view, then click **Run assessment**.

The assessment pipeline runs:
1. **Triage Agent** — classifies the event, identifies urgency signals
2. **Context Agent** — queries all 7 evidence sources (access control, schedule, policy, history, work orders, delivery, camera)
3. **Risk Engine** — deterministic score from DB policy (no LLM)
4. **Confidence Engine** — separate from risk; reduced if sources unavailable
5. **Explanation Agent** — grounded narrative from evidence
6. **Coordinator** (if Orchestrate configured) or deterministic fallback

**Checkpoint:** Status changes to `awaiting_review`.

### Step 5 — Review evidence, risk, and explanation

In the event detail view, confirm:

| Element | Expected content |
|---------|-----------------|
| Risk level | High (≥ 50 score) |
| Risk factors | "No matching authorised badge", "Activity outside permitted schedule", "Restricted location at event time" |
| Confidence | High (all evidence sources healthy) |
| Evidence sources | access\_control, schedule, location\_policy, incident\_history all listed |
| Explanation summary | Grounded narrative referencing the evidence |
| Missing evidence | None (all sources returned) |
| Recommendation | Human review required |

Click **Agent activity** — verify Triage and Context agent results are shown.  
Click **Request coordinator review** — verify the coordinator summary appears.

### Step 6 — Human decision

In the **Human review decision** form:
1. Select decision: `escalate`
2. Enter rationale: `Unverified after-hours access at Loading Dock 3 — escalating to supervisor per protocol.`
3. Click **Record decision**

**Checkpoint:** Event status changes to `escalated`. Escalation record appears in the Escalation panel.

### Step 7 — Audit record

Click **Audit trail** (top nav, supervisor+ role required).

Verify the audit trail shows:
- `event_received` — when the event was created
- `risk_assessed` — when assessment completed
- `human_decision` — the escalate decision with actor and rationale

**Checkpoint:** All actions are immutably recorded. No UPDATE/DELETE controls exist.

### Step 8 — Demonstrate missing-evidence scenario (Scenario C)

```bash
curl -s -X POST http://localhost:8000/api/v1/simulator/events \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"scenario_ids":["demo-scenario-c"]}' \
  | python3 -m json.tool
```

Open the event → Run assessment → observe:
- Confidence reduced (badge and schedule sources show `unavailable`)
- `confidence_reductions` list populated
- Explanation says "cannot confirm or deny" — not "badge was absent"
- `human_review_required: true` remains enforced

### Step 9 — Demonstrate AI-unavailable fallback (Scenario E)

```bash
curl -s -X POST http://localhost:8000/api/v1/simulator/events \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"scenario_ids":["demo-scenario-e"]}' \
  | python3 -m json.tool
```

Run assessment. Even without Orchestrate, the deterministic pipeline completes:
- Risk score is present
- Coordinator review says `source: deterministic_fallback`
- Event is never lost
- Operator can still record a decision

---

## 4. Running the automated smoke test during demonstration

On EC2 (separate terminal from the tunnel terminal):

```bash
cd ~/sentineliq
E2E_ALLOW_PERSISTENT_WRITES=yes \
E2E_EMAIL=e2e-admin@sentineliq.dev \
E2E_PASSWORD=SentinelIQ-E2E-Admin-2026 \
E2E_BASE_URL=http://localhost:8000 \
E2E_PYTHON=/home/ubuntu/sentineliq/backend/.venv/bin/python \
bash scripts/e2e_smoke.sh
```

Expected: 0 failures. All API contracts and safety invariants pass.

---

## 5. Scope freeze

After the demonstration is validated:

1. No new features, endpoints, models, or agent behaviours are added to the
   MVP codebase without explicit approval.
2. Production expansion (Gate 26 onwards) does not begin until approved.
3. Any urgent fix required before Gate 25 sign-off must be treated as a
   release candidate patch, not a feature.

The scope freeze applies to:
- `backend/app/` — all API endpoints, services, models, agents
- `frontend/src/` — all dashboard views and API calls
- `data/scenarios/` — the 24-scenario simulator dataset
- `evaluations/` — the 30-case evaluation dataset and scorer
- `agents/` — all agent definitions and tool schemas

Documentation updates and configuration changes remain permitted.

---

## 6. Gate 25 acceptance criteria

| Criterion | How verified | Status |
|-----------|-------------|--------|
| Simulated event enters the system | Simulator API `POST /events` | ✅ Runnable |
| SentinelIQ ingestion (normalise + store) | Status changes to `normalised` | ✅ Runnable |
| Assessment pipeline runs end-to-end | Status → `awaiting_review` | ✅ Runnable |
| Evidence retrieved from all 7 sources | Evidence panel in dashboard | ✅ Runnable |
| Deterministic risk score produced | Risk score and level visible | ✅ Runnable |
| Confidence calculated independently | Confidence score and reductions visible | ✅ Runnable |
| Explanation grounded in evidence | Explanation summary with cited factors | ✅ Runnable |
| Operator dashboard accessible via browser | SSH tunnel + `http://localhost:3000` | ✅ Runnable |
| Human decision recorded | Decision form submitted successfully | ✅ Runnable |
| Audit record created | Audit trail shows all actions | ✅ Runnable |
| All §52 MVP success criteria met | Gate 24 release candidate §8 | ✅ Complete |
| Automated smoke test passes | `scripts/e2e_smoke.sh` 0 failures | ✅ 108/108 passed (2026-11-09) |
| Scope freeze acknowledged | This document signed off by operator | ⬜ Pending operator sign-off |

---

## 7. Troubleshooting the tunnel

| Symptom | Fix |
|---------|-----|
| `Permission denied (publickey)` | `chmod 400 sentinelIq.pem` and retry |
| `bind: Address already in use` on port 3000 | Another process uses port 3000 locally — use `-L 3001:127.0.0.1:3000` and open `http://localhost:3001` |
| Browser shows `Connection refused` | Check EC2 containers: `docker compose ps`. If `sentineliq-frontend` is not up, run `docker compose up -d` |
| `502 Bad Gateway` in browser | Backend container unhealthy — check `docker compose logs backend` |
| EC2 DNS name changed (instance restarted) | Update the hostname: check the new public DNS in the AWS console and replace `ec2-54-164-137-222.compute-1.amazonaws.com` |
| `This site can't be reached` | The SSH tunnel may have dropped — re-run the tunnel command |
| API returns `401` for all requests | Token expired — log out and back in from the dashboard |

---

## 8. Quick-reference card

```
┌──────────────────────────────────────────────────────────────────┐
│  SentinelIQ — Gate 25 Quick Reference                            │
├──────────────────────────────────────────────────────────────────┤
│  EC2 host:  ec2-54-164-137-222.compute-1.amazonaws.com           │
│  Key file:  sentinelIq.pem                                       │
├──────────────────────────────────────────────────────────────────┤
│  OPEN TUNNEL (run locally):                                      │
│                                                                  │
│  ssh -i "sentinelIq.pem" \                                       │
│      -L 3000:127.0.0.1:3000 \                                    │
│      -N -f \                                                     │
│      ubuntu@ec2-54-164-137-222.compute-1.amazonaws.com           │
├──────────────────────────────────────────────────────────────────┤
│  OPEN BROWSER:  http://localhost:3000                            │
├──────────────────────────────────────────────────────────────────┤
│  DEMO CREDENTIALS:                                               │
│    Email:     demo@sentineliq.dev                                │
│    Password:  SentinelIQ-Demo-2026                               │
├──────────────────────────────────────────────────────────────────┤
│  ALSO FORWARD API (optional):                                    │
│                                                                  │
│  ssh -i "sentinelIq.pem" \                                       │
│      -L 3000:127.0.0.1:3000 \                                    │
│      -L 8000:127.0.0.1:8000 \                                    │
│      -N -f \                                                     │
│      ubuntu@ec2-54-164-137-222.compute-1.amazonaws.com           │
│                                                                  │
│  Swagger UI:  http://localhost:8000/docs                         │
└──────────────────────────────────────────────────────────────────┘
```
