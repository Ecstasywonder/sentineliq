# EC2 Caddy edge proxy

This configuration is the persistent HTTPS edge path for SentinelIQ. It proxies
the browser application to the loopback frontend and proxies `/api/v1/*` and
the minimal `/health` response to the loopback backend. Public `/ready` returns
`404` because it can disclose dependency diagnostics; operators can query it
from the EC2 loopback interface. Docker service ports remain loopback-only; do
not publish them directly for team access.

It requires Caddy **2.11.9 or later**. The configuration deliberately retains
the `shortlived` ACME profile and configures `default_sni` from the same public
host used by the site block.

## Deploy on EC2

1. Set `SENTINELIQ_PUBLIC_HOST` to the exact reachable public DNS name (or the
   current public IP only as a temporary arrangement), and ensure ports 80 and
   443 are reachable so ACME can complete its HTTP challenge. A public IP can
   change after an instance stop/start unless the infrastructure separately
   provides a stable address; this repository does not allocate or claim one.
2. Install the versioned systemd override and its root-owned environment file:

   ```sh
   sudo install -d -o root -g root -m 0755 /etc/systemd/system/caddy.service.d /etc/sentineliq
   sudo install -o root -g root -m 0644 infra/caddy/systemd/caddy.service.d/sentineliq.conf /etc/systemd/system/caddy.service.d/sentineliq.conf
   sudo sh -c 'umask 077; printf "%s\\n" "SENTINELIQ_PUBLIC_HOST=api.example.com" > /etc/sentineliq/caddy.env'
   sudo chown root:root /etc/sentineliq/caddy.env
   sudo chmod 0600 /etc/sentineliq/caddy.env
   sudo install -o root -g root -m 0644 infra/caddy/Caddyfile /etc/caddy/Caddyfile
   sudo systemctl daemon-reload
   sudo systemctl reload caddy
   ```

   Replace `api.example.com` with the exact public host. If using the current
   EC2 instance IP temporarily, update the environment file when that address
   changes.

3. Validate configuration and exposed routes (run the first command before
   reload when making a change):

   ```sh
   sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
   sudo systemctl enable --now caddy
   curl --fail --silent --show-error https://api.example.com/health
   curl --silent --output /dev/null --write-out '%{http_code}\\n' https://api.example.com/ready
   curl --silent --output /dev/null --write-out '%{http_code}\\n' https://api.example.com/
   ```

   The readiness command must print `404`; query detailed readiness locally with
   `curl --fail http://127.0.0.1:8000/ready`. The final command should return the
   frontend application (normally `200`).
   Test an authenticated API route through `/api/v1/` separately; Caddy proxies
   it to the loopback backend at `127.0.0.1:8000`.

## Operating model

`caddy.service` is systemd-managed, so the proxy persists across logout and
restarts when enabled. This does not guarantee a permanent public address or
DNS record: verify the host after infrastructure changes before distributing it
to the team. Use an SSH tunnel only as a private troubleshooting fallback.

Provision separate least-privilege application accounts for team members. Do
not use a shared demo password in a public-facing runbook.
