# SentinelIQ — EC2 Deploy & Test Workflow

**Document ID:** SNTL-EC2-WORKFLOW  
**Version:** 1.0  
**Date:** 2026-11-03

---

## Connection Details

| Item | Value |
|------|-------|
| EC2 Host | `ec2-54-164-137-222.compute-1.amazonaws.com` |
| SSH User | `ubuntu` |
| Key File | `sentinelIq.pem` (must be in your current directory or provide full path) |
| GitHub Remote | `https://github.com/Ecstasywonder/sentineliq.git` |
| Default Branch | `main` |

---

## Workflow Per Gate

After IBM Bob commits a gate locally, you run **Step 1** on your local Git Bash,
then **Step 2** on the EC2 server.

---

## Step 1 — Push from Local Git Bash

Run this in Git Bash from the project root (`SentinelIQ Project/`):

```bash
git push origin main
```

That's it. Everything has already been committed by IBM Bob.

---

## Step 2 — EC2: Pull, Install, Test

SSH in:

```bash
ssh -i "sentinelIq.pem" ubuntu@ec2-54-164-137-222.compute-1.amazonaws.com
```

Then run the following block in one shot (copy-paste the whole thing):

```bash
cd ~/sentineliq && \
git pull origin main && \
cd backend && \
uv pip install --system -e ".[dev]" -q && \
echo "=== RUFF ===" && \
ruff check app tests && \
echo "=== PYTEST ===" && \
APP_ENV=development \
SECRET_KEY=ci-test-secret-key \
DATABASE_URL="sqlite+aiosqlite:///:memory:" \
DATABASE_URL_SYNC="sqlite:///:memory:" \
pytest tests/ -v --tb=short 2>&1 | tee /tmp/pytest-latest.log && \
echo "=== DONE ==="
```

Paste the output back to IBM Bob for gate sign-off.

---

## First-Time EC2 Setup (one time only)

If the repo has not been cloned on EC2 yet:

```bash
ssh -i "sentinelIq.pem" ubuntu@ec2-54-164-137-222.compute-1.amazonaws.com

# On EC2:
cd ~
git clone https://github.com/Ecstasywonder/sentineliq.git sentineliq
cd sentineliq/backend
uv pip install --system -e ".[dev]"
```

---

## Gate-by-Gate Quick Reference

Each gate below lists the exact push + test block to use.  
The EC2 block is identical for every backend-only gate — copy the Step 2 block above.

### Gate 8 — Evidence Aggregation & Assessment API ✅ (already committed)

**Local push:**
```bash
git push origin main
```

**EC2 test block:**
```bash
cd ~/sentineliq && git pull origin main && cd backend && \
uv pip install --system -e ".[dev]" -q && \
ruff check app tests && \
APP_ENV=development SECRET_KEY=ci-test-secret-key \
DATABASE_URL="sqlite+aiosqlite:///:memory:" \
DATABASE_URL_SYNC="sqlite:///:memory:" \
pytest tests/test_assessment_api.py tests/test_evidence_aggregator.py \
  tests/test_risk_engine.py tests/test_confidence_engine.py -v --tb=short
```

**Expected:** All tests green, ruff exits 0.

---

### Gate 9 — Risk Assessment API (next)

*Scripts will be provided at the end of Gate 9.*

---

## Re-running a Single Test File

```bash
ssh -i "sentinelIq.pem" ubuntu@ec2-54-164-137-222.compute-1.amazonaws.com

# On EC2:
cd ~/sentineliq/backend
APP_ENV=development SECRET_KEY=ci-test-secret-key \
DATABASE_URL="sqlite+aiosqlite:///:memory:" \
DATABASE_URL_SYNC="sqlite:///:memory:" \
pytest tests/test_assessment_api.py -v --tb=long
```

---

## Full Suite (all gates)

```bash
cd ~/sentineliq/backend && \
APP_ENV=development SECRET_KEY=ci-test-secret-key \
DATABASE_URL="sqlite+aiosqlite:///:memory:" \
DATABASE_URL_SYNC="sqlite:///:memory:" \
pytest tests/ -v --tb=short --cov=app --cov-report=term-missing
```

---

## Option B — SSH Direct Editing (advanced)

IBM Bob can SSH directly to EC2, edit files, run tests, and push to GitHub —
bypassing the local Windows machine entirely.

**Requirements:**
1. The `sentinelIq.pem` file must be accessible to IBM Bob's tool runtime.
   Place it somewhere Bob can read it, e.g. copy it into the project root
   (it is already in `.gitignore` — `*.pem` — so it will never be committed).
2. Confirm the EC2 GitHub remote uses HTTPS (no deploy key needed for public
   repos, or configure a Personal Access Token for push).

**Once the key is in the project folder**, IBM Bob can run:
```bash
ssh -i "c:/path/to/sentinelIq.pem" ubuntu@ec2-54-164-137-222.compute-1.amazonaws.com \
  "cd ~/sentineliq && git pull && cd backend && pytest tests/ -v --tb=short"
```

**Recommendation:** Use Option B if you want fully automated gate validation.
Just drop `sentinelIq.pem` into the project root and tell IBM Bob — the rest
of the workflow becomes hands-free.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Permission denied (publickey)` | Run `chmod 400 sentinelIq.pem` first |
| `Host key verification failed` | Add `-o StrictHostKeyChecking=no` to the ssh command |
| `ModuleNotFoundError` after pull | Re-run `uv pip install --system -e ".[dev]"` |
| `pytest: command not found` | Run `uv pip install --system pytest pytest-asyncio aiosqlite` |
| `aiosqlite` import error | Run `uv pip install --system aiosqlite` |
| EC2 instance stopped | Start it from AWS Console; public IP/DNS may change |
