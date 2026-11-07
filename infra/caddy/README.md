# EC2 Caddy edge proxy

This configuration exposes only the SentinelIQ API (`/api/v1/*`) and health
endpoint (`/health`) over HTTPS. Every other path returns `404`; it is not a
general-purpose web server.

It requires Caddy **2.11.9 or later**. The configuration deliberately retains
the `shortlived` ACME profile and configures `default_sni` from the same public
host used by the site block.

## Deploy on EC2

1. Prefer a stable DNS name backed by an Elastic IP. Point the DNS A/AAAA
   record at that address and ensure ports 80 and 443 are reachable so ACME can
   complete its HTTP challenge. A raw public IP is less reliable: it changes
   when an instance without an Elastic IP is stopped and started.
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

   Replace `api.example.com` with the exact public DNS name. If using the
   current EC2 instance IP temporarily, set it to that IP and update the
   environment file whenever the instance's public IP changes.

3. Validate configuration and exposed routes (run the first command before
   reload when making a change):

   ```sh
   sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
   curl --fail --silent --show-error https://api.example.com/health
   curl --silent --output /dev/null --write-out '%{http_code}\\n' https://api.example.com/
   ```

   The final command must print `404`. Test an authenticated API route through
   `/api/v1/` separately; Caddy proxies it to the loopback backend at
   `127.0.0.1:8000`.
