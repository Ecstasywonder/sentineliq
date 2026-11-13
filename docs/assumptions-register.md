# SentinelIQ — Assumptions Register

**Maintained by:** IBM Bob (Principal Architect)  
**Last updated:** 2026-11-03  
**Gate:** 0

This register records all assumptions made during the design and implementation of SentinelIQ. Each assumption is tracked with its potential impact and the responsible party for confirming or correcting it.

---

## Format

| Field | Description |
|-------|-------------|
| **ID** | Stable identifier (A-NN) |
| **Assumption** | What is being assumed |
| **Gate Relevant** | When this assumption matters most |
| **Impact if Wrong** | What breaks or changes if the assumption is incorrect |
| **Owner** | Who is responsible for confirming this |
| **Status** | Open / Confirmed / Invalidated |
| **Resolution** | How it was resolved (if applicable) |

---

## Environment Assumptions

| ID | Assumption | Gate | Impact if Wrong | Owner | Status |
|----|-----------|------|----------------|-------|--------|
| A-01 | EC2 runs Ubuntu 22.04 LTS or 24.04 LTS | 0 | Bootstrap script may need OS-specific adjustments | Project Owner | Confirmed — Ubuntu (ip-172-31-18-119) |
| A-02 | EC2 has outbound internet access for apt/pip/npm | 0–2 | Bootstrap fails; offline mirror needed | Project Owner | Confirmed — all packages installed successfully |
| A-03 | EC2 has ≥4 GB RAM, ≥20 GB disk, ≥2 vCPU | 0–2 | Performance degradation; instance resize required | Project Owner | Confirmed — 7.6 GiB RAM, 61G disk, 58G free |
| A-04 | Docker can be installed on the EC2 instance | 2 | Container workflow fails; bare-metal install needed | Project Owner | Confirmed — Docker 29.9.2 installed |
| A-05 | EC2 security group allows inbound SSH (port 22) | 0 | Cannot connect | Project Owner | Confirmed |
| A-06 | EC2 security group allows inbound port 8000 for dev | 2 | Cannot test backend from developer machine | Project Owner | Open |

## Toolchain Assumptions

| ID | Assumption | Gate | Impact if Wrong | Owner | Status |
|----|-----------|------|----------------|-------|--------|
| A-07 | Git repo will be hosted on GitHub | 0–2 | CI config (GitHub Actions) will need adjustment | Project Owner | Open |
| A-08 | uv is compatible with all required Python packages | 2 | Fall back to pip; minor speed/reproducibility impact | Architect | Open |
| A-09 | Python 3.11 or 3.12 will be available via deadsnakes PPA | 2 | Use pyenv or build from source | Architect | Open |

## IBM Platform Assumptions

| ID | Assumption | Gate | Impact if Wrong | Owner | Status |
|----|-----------|------|----------------|-------|--------|
| A-10 | A watsonx Orchestrate tenant will be available from Gate 7 | 7 | Agent work blocked; stubs maintained | Project Owner | Open |
| A-11 | watsonx Orchestrate supports Python tool functions via ADK | 7 | Tool implementation approach may differ | Architect | Open |
| A-12 | Orchestrate ADK is installable via pip on Ubuntu | 7 | Alternative install path needed | Architect | Open |
| A-13 | Model inference is available through watsonx Orchestrate, not direct watsonx.ai Chat API | 11–14 | A tenant/runtime failure would require deterministic safety fallback, not silent provider substitution | Architect | Confirmed — EC2 live tool/collaborator and specialist-run evidence on 2026-11-13; Path-A removal remains pending merge/deploy |

## Database Assumptions

| ID | Assumption | Gate | Impact if Wrong | Owner | Status |
|----|-----------|------|----------------|-------|--------|
| A-14 | PostgreSQL will run in Docker on the EC2 instance (not managed RDS) | 3 | Connection strings and migration approach differ | Architect | Open |
| A-15 | pgvector extension is available for PostgreSQL 15+ | 8 | Use separate vector store (Qdrant) or text search | Architect | Open |
| A-16 | PostgreSQL 15 is sufficient for all data model requirements | 3 | Upgrade required if JSON/array features are insufficient | Architect | Open |

## Product Scope Assumptions

| ID | Assumption | Gate | Impact if Wrong | Owner | Status |
|----|-----------|------|----------------|-------|--------|
| A-17 | No live CCTV integration is required for MVP | 0–25 | Simulator must be expanded | Project Owner | Confirmed |
| A-18 | No production biometrics at any gate | All | Fundamental architecture change; out of scope | Architect | Confirmed |
| A-19 | Solution Design PDF is consistent with the Master Build Prompt | 1 | BRD may need reconciliation | Project Owner | Confirmed — PDF reviewed 2026-11-03; fully consistent. Persona (Musa/Maya) added to BRD. |
| A-20 | Single EC2 instance is sufficient for MVP (Gates 0–25) | 0–25 | May need instance resize or multi-instance for load testing | Architect | Open |
| A-21 | The primary operator UI is a web dashboard (not mobile-first) | 16 | Responsive design approach changes | Project Owner | Open |

## Integration Assumptions

| ID | Assumption | Gate | Impact if Wrong | Owner | Status |
|----|-----------|------|----------------|-------|--------|
| A-22 | Access control, schedule, and policy data are available as mock/local for MVP | 4–6 | Real adapters needed earlier | Architect | Confirmed |
| A-23 | Semantic search will use pgvector (not a separate vector database) | 8 | Add Qdrant or similar to infrastructure | Architect | Open |
| A-24 | Email/SMS notification is out of scope for MVP | 15–17 | Notification adapter design changes | Project Owner | Open |
| A-25 | Physical security actuators (door locks, alarms) are permanently out of scope | All | Fundamental product safety violation | Architect | Confirmed |

## Security Assumptions

| ID | Assumption | Gate | Impact if Wrong | Owner | Status |
|----|-----------|------|----------------|-------|--------|
| A-26 | JWT-based authentication is sufficient for MVP (not SSO/OIDC) | 19 | SSO integration required from Gate 34 | Architect | Open |
| A-27 | HTTPS/TLS termination occurs at a load balancer/proxy (not app layer) for production | 35 | App-layer TLS configuration needed | Architect | Open |
| A-28 | Secret management will use environment variables for MVP, graduating to a vault for production | 2, 35 | Vault integration earlier than planned | Architect | Open |

---

## Invalidated Assumptions

*(None yet — updated as assumptions are confirmed or invalidated)*

---

## Review Schedule

This register must be reviewed at each gate completion. Any newly discovered assumption must be added immediately when identified.
