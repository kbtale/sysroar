# Changelog

All notable changes to SysRoar are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-11-28

### Added
- **Production Stack:** `docker-compose.prod.yml` with Caddy auto-TLS + built Vue SPA, Gunicorn + Uvicorn HTTP workers, dedicated Uvicorn WebSocket service, ingest consumer, Celery worker, single beat, TimescaleDB PG15, and password-protected Redis 7.
- **Backups & Kubernetes:** Automated TimescaleDB `pg_dump` / `pg_restore` scripts with SHA-256 checksums, `--profile backups` sidecar, Kubernetes Helm chart (`deploy/helm/sysroar/`), and `docs/UPGRADING.md`.
- **Demo Mode:** `docker compose --profile demo up` launching a 10-server simulated fleet with 6-hour diurnal backfill, spikes, flapping host, uptime checks, and `/status/demo`.
- **Docs & Release Automation:** VitePress documentation site under `docs/`, GitHub Pages docs workflow, and semantic-versioned GHCR release workflow (`.github/workflows/release.yml`).

## [0.4.0] - 2026-11-27

### Added
- **Rust Agent v2 (`0.2.0`):** CPU iowait/steal, mount inodes, disk IOPS, top processes, temperatures, Docker container stats (`bollard`), systemd units, optional log shipper, one-line Linux/macOS/Windows installers, and Ed25519 signed auto-update.
- **Uptime Checks:** HTTP status/keyword, TCP, SSL certificate expiry, DNS, and Ping monitors with SSRF guard and automatic incident lifecycle integration.
- **10 Native Notification Channels:** Email, Signed Webhook, Slack, Discord, Microsoft Teams, Telegram, PagerDuty, Opsgenie, ntfy, and Gotify routed through `send_safe_webhook_post`.
- **Noise Reduction:** Recurring maintenance windows, simultaneous alert grouping per channel, and hourly-scheduled daily digest emails.
- **Public Status Pages:** Zero-leakage unauthenticated `/status/<slug>` pages built from selected servers and uptime checks.
- **Open Ingestion:** OTLP/HTTP JSON (`POST /api/telemetry/otlp/v1/metrics`) and Snappy-compressed Prometheus remote-write (`POST /api/telemetry/prometheus/remote-write`).
- **Pluggable Logs & Anomaly Hints:** `LogBackend` interface (`none`, `loki` with `X-Scope-OrgID`, `elasticsearch`), `--profile logs` (Vector + Loki), log-based alert rules, Logs Explorer UI with WebSocket live tail, and rolling z-score anomaly badges.

## [0.3.0] - 2026-11-26

### Added
- **Product UI MVP:** Vue 3 + TypeScript + `@ui-sdk/vue` frontend with first-run setup wizard, Fleet Overview, Server Detail time-series charts, Alerts/Incidents/Silences console, RBAC Team & Keys Settings, live WebSocket streaming, dark/light themes, and Playwright E2E CI suite.

## [0.2.0] - 2026-11-25

### Added
- **Security & Multi-Tenancy Hardening:** Scoped `AgentKey` and `EnrollmentToken` auth, HttpOnly session cookie auth with CSRF + `django-axes` lockout, RBAC (`owner`/`admin`/`member`/`viewer`), tenant-scoped audit logs, SSRF guard + HMAC webhook signing, security headers, and generated OpenAPI schema.

## [0.1.0] - 2026-11-24

### Added
- **Reliability Core:** Clean TimescaleDB hypertable + continuous aggregate migrations, Redis Streams durable ingestion consumer with DLQ, transactional `NotificationOutbox` with exponential backoff, Redis heartbeat tracker, alert state machine with hysteresis and escalating cooldowns, `/healthz`, `/readyz`, `/metrics`, and Rust agent v1 with SQLite disk buffer.
