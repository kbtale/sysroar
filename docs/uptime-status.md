# Uptime Checks & Public Status Pages

## Uptime Checks

Uptime checks run from the SysRoar server via Celery Beat every 30 seconds (honoring each check's `interval_seconds`):

- **HTTP / HTTPS:** Status code match, optional response body keyword check, and TLS certificate expiration tracking.
- **TCP Port:** Socket reachability and handshake latency.
- **SSL Certificate:** Standalone TLS certificate expiration warning (`degraded`) and expiry (`down`).
- **DNS Lookup:** Hostname resolution and lookup latency.
- **Ping:** Host reachability and latency probe.

All targets are checked against the SSRF guard by default. Private LAN targets require explicit opt-in via `allow_private_targets=true`. Down or degraded checks automatically open and resolve incidents and notify the attached channel.

## Public Status Pages

Create one or more status pages per tenant under **Settings -> Status Pages**:

- Choose a unique URL slug published at `/status/<slug>` (backed by unauthenticated `GET /api/public/status/<slug>/`).
- Select which uptime checks and servers appear on the page.
- Toggle visibility (`is_public`) and recent 7-day incident timeline (`show_incidents`).
- **Zero-leakage projection:** Public endpoints expose only component display names, operational status, 24h uptime percentages, status bars, and incident titles/timestamps. Internal IPs, hostnames, probe URLs, emails, and tenant IDs are never included.
