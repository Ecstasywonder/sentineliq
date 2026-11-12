# Gate 25 — MVP demonstration and freeze

**Status:** 🔲 Pending release verification and operator demonstration

Gate 25 is the operator demonstration and explicit scope-freeze gate. It must
not be started from historical validation totals or a local/EC2 checkout that
has not been reconciled with the verified `main` commit.

## Team access: persistent HTTPS path

The intended team path is the EC2 systemd-managed Caddy service. It terminates
HTTPS and proxies the browser application to loopback-only frontend and backend
containers. This survives shell logout and instance reboot as long as the Caddy
service, instance, firewall rules, and configured public host remain available.

The deployment operator must publish the verified public host after Caddy has
been validated; it is intentionally not hard-coded here because this document
does not establish a stable DNS name or Elastic IP.

```text
https://<verified-sentineliq-public-host>/
```

Before inviting a team, validate the deployed commit and these routes from a
separate network:

```bash
curl --fail --silent --show-error https://<verified-sentineliq-public-host>/health
test "$(curl --silent --output /dev/null --write-out '%{http_code}' \
  https://<verified-sentineliq-public-host>/ready)" = 404
```

Do not expose container ports 3000, 5432, or 8000 directly. Caddy is the only
intended public entry point. See [`infra/caddy/README.md`](../infra/caddy/README.md)
for configuration and service verification.

### Team accounts

Provision one least-privilege account per team member through the approved
administrative workflow. Do not distribute a shared demo account or a plaintext
password in documentation, chat, shell history, or screenshots. Retain the
account owner, assigned role, and revocation procedure in the deployment record.

### SSH tunnel fallback

An SSH tunnel is a private troubleshooting fallback, not the team-access path:

```bash
ssh -i "<key-file>" -L 3000:127.0.0.1:3000 -N ubuntu@<ec2-host>
```

Open `http://localhost:3000` only on the authenticated operator’s machine.
Use a distinct local port if 3000 is already occupied. This tunnel is not
persistent or shareable with the team.

## EC2 pre-flight

Run these checks on the reconciled, verified release commit. Use an isolated
test worktree for validation; deploy only the commit that subsequently passes
protected-branch CI and merges to `main`.

```bash
git status --short
git rev-parse HEAD
git fetch origin
git rev-parse origin/main
docker compose --env-file .env -f infra/docker/docker-compose.yml ps
curl --fail --silent --show-error http://127.0.0.1:8000/health
curl --fail --silent --show-error http://127.0.0.1:8000/ready
```

Apply migrations and seed only according to the environment’s runbook. Do not
run destructive database reset commands against the shared demonstration
database.

## Demonstration flow

1. Sign in with the demonstrator’s individually provisioned account.
2. Select an event created through the authorized event-ingestion workflow.
   Production startup rejects `ENABLE_SIMULATOR_API=true`, so do not expose or
   enable the simulator on the team deployment. If a canonical scenario is
   needed, prepare it in a separate controlled non-production environment and
   carry only its sanitized result into the demonstration record.

3. Assess the selected event using `POST /api/v1/events/{id}/assess`.
4. In the dashboard, review risk, confidence, evidence limitations, explanation,
   recommendation, and human-review requirement.
5. Record an authorized human decision and confirm its audit entry.
6. Demonstrate the repaired Gate 23 scenarios only after the runner’s EC2
   evidence has been recorded. Do not assert Scenario C–E behaviours merely
   from their simulator payloads.

## Orchestrate requirement

The demonstration must show the verified watsonx Orchestrate path for the
required agents and coordinator, including structured output and tool/collaborator
execution where applicable. Deterministic behaviour remains the safe failure
path, but it is not evidence that Gate 14 is complete.

## Acceptance record

Complete this table only after the release candidate is verified and the
operator demonstration occurs:

| Criterion | Evidence to record | Status |
|---|---|---|
| Reconciled `main` deployment | Commit SHA and deployment timestamp | Pending |
| Caddy team URL works over HTTPS | Public-host route checks and service status | Pending |
| Individual operator access | Provisioning and role verification record | Pending |
| End-to-end assessment | Event ID and sanitized outcome | Pending |
| Live Orchestrate workflow | Sanitized AgentRun/tool evidence | Pending |
| Human decision and immutable audit | Event ID and audit record | Pending |
| Gate 23 runner | 73/73 assertions at candidate `993c0fe`; repeat only if candidate changes materially | Candidate passed |
| Release CI | Actions run `43232697244` for `993c0fe`; final merged SHA still required | Candidate passed |
| Operator scope-freeze approval | Named approval and date | Pending |

After explicit operator approval, freeze MVP scope. Any urgent correction before
sign-off remains a release-candidate patch, not a new feature.
