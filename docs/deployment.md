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

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies (including dev/test extras)
pip install uv
uv pip install -e ".[dev]"

# Install aiosqlite for in-memory test DB
uv pip install aiosqlite

# Run tests
APP_ENV=development \
SECRET_KEY=test-secret-key \
DATABASE_URL="sqlite+aiosqlite:///:memory:" \
DATABASE_URL_SYNC="sqlite:///:memory:" \
pytest tests/ -v
```

## Running Frontend Tests (on EC2, without Docker)

```bash
cd ~/sentineliq/frontend

# Install dependencies
npm ci

# Run unit tests
npm run test:unit

# Type check
npm run typecheck

# Build
npm run build
```

## Running Linting

```bash
# Backend
cd ~/sentineliq/backend
ruff check app tests
ruff format --check app tests

# Frontend
cd ~/sentineliq/frontend
npm run lint
npm run format:check
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
