# ADR-002 — EC2-Based Development and Deployment Strategy

**Date:** 2026-11-03  
**Status:** Accepted  
**Author:** IBM Bob (Principal Architect)  
**Deciders:** Project Owner, Principal Architect

---

## Context

The local development machine (Windows 10) does not have Python, Node.js, or Docker accessible from the command line. The project requires a working build, test, and runtime environment throughout development.

The project owner has an AWS EC2 instance (`ubuntu@98.81.243.2`) available for development use.

---

## Decision

All build, test, and runtime execution will occur on the EC2 server.

**Workflow:**

1. IBM Bob creates and edits all source files in the local `SentinelIQ Project` workspace
2. Changes are committed and pushed to a Git repository (GitHub)
3. On EC2, the repository is cloned/pulled and commands are executed
4. Command output is relayed back to IBM Bob for validation
5. IBM Bob interprets results and continues development

**File authority:** The local workspace (and Git repository) is the canonical source of truth. EC2 is the execution environment.

---

## Rationale

- EC2 provides a clean Ubuntu Linux environment with full package manager access
- Avoids Windows PATH, WSL, and Docker Desktop complications
- Matches production deployment target (Linux containers)
- Git-based relay ensures all changes are version-controlled
- EC2 t3.medium or larger provides sufficient resources for MVP

---

## Alternatives Considered

| Alternative | Reason Not Selected |
|------------|---------------------|
| Fix local Windows environment | Time-consuming; Docker Desktop requires WSL2 distribution; doesn't match prod |
| WSL2 on local machine | WSL has no installed distribution; would need setup time |
| GitHub Codespaces | Viable, but EC2 already available and more configurable |
| Direct SSH MCP tool | No live SSH MCP tool available in current Bob environment |

---

## Consequences

- All shell commands in documentation must use bash/Linux syntax
- Path separators in scripts must use `/` (not `\`)
- EC2 instance must remain available and accessible during development
- If EC2 is terminated or replaced, bootstrap script re-provisions a new instance
- CI/CD (GitHub Actions) will independently validate all changes on Linux runners

---

## Security Implications

- EC2 instance should use a security group restricting SSH to known IPs
- The `.pem` key file must never be committed to the repository (covered by `.gitignore`)
- EC2 instance should not expose unnecessary ports to the public internet
- During development, only ports 22 (SSH), 8000 (backend), 3000 (frontend), 5432 (DB — internal only) need to be accessible

---

## Migration Impact

N/A — development environment decision.

---

## Test Impact

All tests are designed to run on Linux. CI (GitHub Actions) uses Ubuntu runners, ensuring consistency with the EC2 environment.
