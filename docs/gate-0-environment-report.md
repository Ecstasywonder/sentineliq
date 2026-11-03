# Gate 0 — Environment & Source-of-Truth Validation Report

**Date:** 2026-11-03  
**Gate:** 0  
**Status:** Complete  
**Author:** IBM Bob (Principal Architect)

---

## 1. Workspace Inspection

### Local Machine (Windows 10 x64)

| Item | Finding |
|------|---------|
| OS | Windows 10 (Build 19045), x64 |
| Shell | PowerShell 5.1 |
| Git | ✅ git 2.56.0 (C:\Program Files\Git) |
| Python | ⚠️ Microsoft Store stub only — not a real Python installation |
| Node.js | ❌ Not found |
| npm | ❌ Not found |
| Docker CLI | ❌ Not on PATH |
| Docker Desktop | ⚠️ Installed (AppData\Local\Docker) but CLI not accessible from PowerShell |
| WSL | ⚠️ Installed but no distributions loaded |
| IBM Bob | ✅ Installed (C:\Users\...\AppData\Local\Programs\IBM Bob) |

### Conclusion

The local Windows machine does not have a usable Python, Node, or Docker CLI environment. All build, test, and runtime work will execute on the remote EC2 server. The local workspace serves as the **source-code authority** — files are authored here and deployed to EC2 via Git.

---

## 2. Deployment Strategy

```
IBM Bob (local)          Git Repository          EC2 Server
     │                        │                       │
     │  scaffold + edit ──►   │                       │
     │                        │   git push ──────►    │
     │                        │                       │  docker compose up
     │                        │                       │  pytest / vitest
     │  ◄── paste output ─────────────────────────── │
```

**Workflow:**
1. IBM Bob creates/edits all files in the local `SentinelIQ Project` workspace
2. You push to a Git repository (GitHub recommended)
3. On EC2, you `git pull` and run provided commands
4. You paste command output back for validation

---

## 3. EC2 Target Environment

**Connection:** `ssh -i ~/.ssh/"test key.pem" ubuntu@98.81.243.2`  
**Expected OS:** Ubuntu (AWS EC2, likely Ubuntu 22.04 LTS or 24.04 LTS)

### Required EC2 Runtimes (to be installed via bootstrap script)

| Runtime | Required Version | Purpose |
|---------|-----------------|---------|
| Python | 3.11+ | Backend (FastAPI) |
| pip / uv | Latest | Python package management |
| Node.js | 20 LTS | Frontend (React/Vite) |
| npm | 10+ | Frontend packages |
| Docker Engine | 25+ | Container runtime |
| Docker Compose | v2 (plugin) | Multi-service orchestration |
| PostgreSQL | 15+ (via Docker) | Operational database |
| Git | 2.x | Already present on EC2 likely |
| curl / jq | Latest | Scripting utilities |

### EC2 Bootstrap Script

Located at: `infra/docker/bootstrap-ec2.sh`  
Run once on a fresh EC2 Ubuntu instance to install all required runtimes.

---

## 4. Source-of-Truth Documents

### Product Source of Truth

| Document | Location | Status |
|----------|----------|--------|
| Master Build Prompt | Governing prompt provided by project owner | ✅ Active |
| Solution Design PDF | `SentinelIQ_IBM_ELL_Solution_Design_Template.pdf` | ⚠️ PDF format — not directly readable; principles captured in this report |
| BRD | `docs/sentinel-brd.md` | 🔲 Gate 1 |
| SOP | `docs/sentinel-sop.md` | 🔲 Gate 1 |
| Architecture | `docs/architecture.md` | 🔲 Gate 1 |

### Reconciliation Note — Solution Design PDF

The Solution Design PDF was not machine-readable via current tooling (PDF format not supported by `office_read`). The Master Build Prompt is the primary governing specification. Key product principles extracted:

- SentinelIQ is a **post-detection decision-support platform**, not a detection system
- Core value: contextual reasoning + evidence synthesis + transparent risk + human oversight
- Target user: Security Monitoring Officer under time pressure
- IBM watsonx Orchestrate is the agent runtime
- Human authority over every security decision is non-negotiable

---

## 5. watsonx Orchestrate Environment

| Item | Status | Notes |
|------|--------|-------|
| Orchestrate tenant | 🔲 Not yet configured | Required from Gate 7 onward |
| Orchestrate ADK | 🔲 Not yet installed | Will be installed on EC2 |
| Agent definitions | 🔲 Pending Gate 11–14 | |
| Tool schemas | 🔲 Pending Gate 7 | |
| Evaluation framework | 🔲 Pending Gate 21 | |

**Action required (deferred to Gate 7):** You will need to provide your watsonx Orchestrate tenant URL and API key before agent assets can be deployed. This will be stored in `backend/.env` (never in source code).

---

## 6. IBM Bob Capabilities Confirmed

- ✅ File creation, editing, and scaffolding
- ✅ Code generation (Python, TypeScript, SQL, YAML, Bash)
- ✅ Documentation generation
- ✅ Architecture decision records
- ✅ Test generation
- ✅ Docker / CI configuration
- ✅ IBM documentation lookup (`search_ibm_docs`)
- ⚠️ Cannot execute commands on remote EC2 directly — uses relay model described above

---

## 7. Assumptions Register

| ID | Assumption | Impact if Wrong | Owner |
|----|-----------|----------------|-------|
| A-01 | EC2 instance is Ubuntu 22.04 LTS or 24.04 LTS | Bootstrap script may need adjustment | You |
| A-02 | EC2 instance has internet access for package installation | Bootstrap will fail; use offline mirror | You |
| A-03 | EC2 instance has at least 4 GB RAM and 20 GB disk | Performance degraded; resize instance | You |
| A-04 | You will provide a watsonx Orchestrate tenant for agent work | Gates 7–14 cannot be completed | You |
| A-05 | Git repo will be hosted on GitHub (default) | CI config will target GitHub Actions | You |
| A-06 | PostgreSQL will run in Docker on EC2 (not managed RDS) | Connection strings/migration approach differs | Architect |
| A-07 | No live CCTV integration in MVP | MVP uses simulator only | Architect |
| A-08 | No production biometrics at any stage | Out of scope permanently | Architect |
| A-09 | Solution Design PDF contents are consistent with Master Build Prompt | BRD may need reconciliation | You |
| A-10 | Single EC2 instance is sufficient for MVP development | May need to scale for load testing (Gate 39) | Architect |

---

## 8. Blockers

| ID | Blocker | Severity | Resolution |
|----|---------|----------|-----------|
| B-01 | Python / Node not on local PATH | Medium | Resolved — all execution on EC2 |
| B-02 | Docker CLI not accessible locally | Medium | Resolved — all execution on EC2 |
| B-03 | Solution Design PDF unreadable | Low | Governing prompt is primary spec |
| B-04 | watsonx Orchestrate credentials not yet provided | Medium | Deferred to Gate 7 — not needed for Gates 1–6 |
| B-05 | Git remote not yet configured | Low | Required before EC2 deployment; easy to add |

---

## 9. Proposed Repository Structure

```
sentineliq/
├── docs/
│   ├── adr/                         # Architecture Decision Records
│   ├── gate-0-environment-report.md # This document
│   ├── sentinel-brd.md              # Gate 1
│   ├── sentinel-sop.md              # Gate 1
│   ├── architecture.md              # Gate 1
│   ├── threat-model.md              # Gate 1
│   ├── api-contracts.md             # Gate 1
│   ├── data-model.md                # Gate 3
│   ├── agent-design.md              # Gate 11
│   ├── risk-model.md                # Gate 9
│   ├── evaluation-plan.md           # Gate 21
│   └── deployment.md                # Gate 2
│
├── frontend/                        # React 18 + TypeScript + Vite
│   ├── src/
│   └── tests/
│
├── backend/                         # Python 3.11 + FastAPI
│   ├── app/
│   │   ├── api/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── services/
│   │   ├── repositories/
│   │   ├── security/
│   │   ├── audit/
│   │   └── integrations/
│   └── tests/
│
├── agents/                          # Orchestrate agent definitions (YAML + prompts)
├── workflows/                       # Orchestrate workflow definitions
├── tools/                           # Orchestrate tool implementations (Python)
├── data/                            # Seed data + test scenarios
├── evaluations/                     # Evaluation datasets + expected outputs
│
└── infra/
    ├── docker/
    │   ├── bootstrap-ec2.sh         # EC2 one-time setup
    │   ├── docker-compose.yml       # Local/EC2 development stack
    │   ├── Dockerfile.backend
    │   └── Dockerfile.frontend
    ├── ci/
    │   └── .github/workflows/ci.yml
    └── deployment/
```

---

## 10. Next Gate

**Gate 1 — BRD, SOP and Architecture Specification**

Will produce:
- `docs/sentinel-brd.md` — full Business Requirements Document
- `docs/sentinel-sop.md` — Standard Operating Procedure for the platform
- `docs/architecture.md` — system context, logical architecture, data flow
- `docs/threat-model.md` — initial threat model
- `docs/api-contracts.md` — API surface definition
- `docs/adr/ADR-001-*.md` — initial Architecture Decision Records
- Acceptance criteria for the specification

---

## Acceptance Criteria — Gate 0

- [x] Workspace inspected
- [x] Local toolchain gaps identified
- [x] EC2 deployment strategy defined
- [x] Bootstrap script created (`infra/docker/bootstrap-ec2.sh`)
- [x] IBM Bob capabilities confirmed
- [x] watsonx Orchestrate status assessed
- [x] Assumptions register created
- [x] Blockers identified
- [x] Repository structure created
- [x] Source-of-truth hierarchy established
- [x] Gate 0 report written
