# SentinelIQ — Local Development & EC2 Deployment

## Prerequisites

All commands run on the **EC2 server** unless otherwise noted.

## First-Time Setup on EC2

```bash
# 1. Clone the repo (after pushing from local)
git clone git@github.com:YOUR_USERNAME/sentineliq.git ~/sentineliq
cd ~/sentineliq

# 2. Create backend .env
cp backend/.env.example backend/.env
# Edit backend/.env — set SECRET_KEY at minimum:
#   SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")

# 3. Start services
docker compose -f infra/docker/docker-compose.yml up -d

# 4. Verify health
curl http://localhost:8000/health
curl http://localhost:8000/ready
```

## Running Backend Tests (on EC2, without Docker)

```bash
cd ~/sentineliq/backend

# Install python3.14-venv (required for venv on Ubuntu with Python 3.14)
sudo apt-get install -y python3.14-venv

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# uv is already in ~/.local/bin from bootstrap — ensure it's on PATH
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

# Install dependencies (including dev/test extras) + aiosqlite for tests
uv pip install -e ".[dev]"
uv pip install aiosqlite

# Run tests
APP_ENV=development \
SECRET_KEY=test-secret-key \
DATABASE_URL="sqlite+aiosqlite:///:memory:" \
DATABASE_URL_SYNC="sqlite:///:memory:" \
pytest tests/ -v
```

## Running Backend Lint (via uv tools)

```bash
cd ~/sentineliq/backend
source .venv/bin/activate

# ruff is installed as part of [dev] extras — run via python -m
python -m ruff check app tests
python -m ruff format --check app tests

# mypy
python -m mypy app --ignore-missing-imports
```

## Running Frontend Tests (on EC2, without Docker)

```bash
cd ~/sentineliq/frontend

# Generate package-lock.json first (required for npm ci)
npm install

# Now run tests and build
npm run typecheck
npm run test:unit
npm run build
```

## Docker Compose Operations

```bash
# Start all services
docker compose -f infra/docker/docker-compose.yml up -d

# View logs
docker compose -f infra/docker/docker-compose.yml logs -f backend

# Stop all services
docker compose -f infra/docker/docker-compose.yml down

# Stop and remove volumes (WARNING: deletes data)
docker compose -f infra/docker/docker-compose.yml down -v

# Rebuild images
docker compose -f infra/docker/docker-compose.yml build --no-cache
```

## Apply Database Migrations

```bash
# Inside the backend container
docker compose -f infra/docker/docker-compose.yml exec backend alembic upgrade head

# Or directly on EC2 with venv active
cd ~/sentineliq/backend
source .venv/bin/activate
alembic upgrade head
```

## Useful Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Liveness check |
| `GET /ready` | Readiness check (DB connectivity) |
| `GET /api/v1/system/info` | App info and feature flags |
| `GET /docs` | Swagger UI (dev only) |
| `GET /openapi.json` | OpenAPI schema |

## Running Gate 4 Tests — Risk Engine & Confidence Engine

```bash
cd ~/sentineliq/backend
source .venv/bin/activate

# Run only Gate 4 engine tests (fast — SQLite in-memory, no postgres needed)
APP_ENV=development \
SECRET_KEY=test-secret-key \
DATABASE_URL="sqlite+aiosqlite:///:memory:" \
DATABASE_URL_SYNC="sqlite:///:memory:" \
  pytest tests/test_risk_engine.py tests/test_confidence_engine.py -v

# Run the full test suite
APP_ENV=development \
SECRET_KEY=test-secret-key \
DATABASE_URL="sqlite+aiosqlite:///:memory:" \
DATABASE_URL_SYNC="sqlite:///:memory:" \
  pytest tests/ -v
```

**Expected:** all tests pass, coverage report printed.

## Running Gate 5 Tests — Event Ingestion API

```bash
cd ~/sentineliq/backend
source .venv/bin/activate

APP_ENV=development \
SECRET_KEY=test-secret-key \
DATABASE_URL="sqlite+aiosqlite:///:memory:" \
DATABASE_URL_SYNC="sqlite:///:memory:" \
  pytest tests/test_events_api.py -v

# Full suite
APP_ENV=development \
SECRET_KEY=test-secret-key \
DATABASE_URL="sqlite+aiosqlite:///:memory:" \
DATABASE_URL_SYNC="sqlite:///:memory:" \
  pytest tests/ -v
```

## Gate 5 API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/events` | Ingest a security event (201 new, 200 duplicate) |
| `GET` | `/api/v1/events` | Paginated event queue (`?status=&risk_level=&page=&page_size=`) |
| `GET` | `/api/v1/events/{id}` | Retrieve single event by ID |
| `PATCH` | `/api/v1/events/{id}/status` | Advance event lifecycle status |


## Running Gate 6 Tests — Auth & RBAC

```bash
cd ~/sentineliq/backend
source .venv/bin/activate

APP_ENV=development \
SECRET_KEY=test-secret-key \
DATABASE_URL="sqlite+aiosqlite:///:memory:" \
DATABASE_URL_SYNC="sqlite:///:memory:" \
  pytest tests/test_auth.py -v

# Full suite
APP_ENV=development \
SECRET_KEY=test-secret-key \
DATABASE_URL="sqlite+aiosqlite:///:memory:" \
DATABASE_URL_SYNC="sqlite:///:memory:" \
  pytest tests/ -v
```

## Gate 6 Auth Endpoints

| Method | Path | Auth Required | Description |
|--------|------|--------------|-------------|
| `POST` | `/api/v1/auth/token` | No | Login — returns access + refresh tokens |
| `POST` | `/api/v1/auth/refresh` | No | Exchange refresh token for new access token |
| `GET` | `/api/v1/auth/me` | Yes (Bearer) | Return current user identity |

## Testing with a Real Token (on EC2, after seeding)

```bash
# Seed the database first
cd ~/sentineliq/backend
source .venv/bin/activate
DATABASE_URL="postgresql+asyncpg://sentineliq:changeme_dev_only@localhost:5432/sentineliq" \
  python -m app.db.seed

# Login and capture token
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/token \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@sentineliq.dev","password":"changeme"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Use token
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/events
```

