# SysRoar

Self-hosted, open-source, multi-tenant server monitoring for small teams and MSPs: one-line Rust agent, TimescaleDB rollups, real-time fleet view, smart alerts that do not spam, uptime checks, public status pages, OTLP/Prometheus open ingestion, and optional multi-tenant logs.

## Highlights

- **Rust Agent v2 (`agent/`):** Single static binary (`#![forbid(unsafe_code)]`) with SQLite disk buffering, gzip batching, CPU iowait/steal, mount inodes, disk IOPS, top processes, temperatures, Docker container stats (`bollard`), systemd units, optional log shipping, and Ed25519 signed auto-updates.
- **High-Throughput Pipeline:** Django 6 + DRF -> Redis Streams (`XADD` / `XREADGROUP`) -> TimescaleDB hypertables + continuous aggregates (`5m` and `1h` rollups) + Channels WebSockets.
- **Smart Alerting:** Durable state machine with pending durations, hysteresis, escalating cooldowns, 10 native SSRF-guarded notification channels (Email, Signed Webhook, Slack, Discord, Teams, Telegram, PagerDuty, Opsgenie, ntfy, Gotify), silences, recurring maintenance windows, simultaneous alert grouping, daily digest emails, and z-score anomaly hints.
- **Uptime & Public Status Pages:** Built-in HTTP/TCP/SSL/DNS/Ping monitors and zero-leakage unauthenticated `/status/<slug>` pages.
- **Open Ingestion:** Native `POST /api/telemetry/otlp/v1/metrics` (OTLP/HTTP JSON + gzip) and `POST /api/telemetry/prometheus/remote-write` (Snappy protobuf).
- **Pluggable Multi-Tenant Logs (Off by Default):** Keep `LOG_BACKEND=none` for minimal footprint, or enable `--profile logs` (Vector + Loki with `X-Scope-OrgID` tenant isolation) or `--profile elk` (Elasticsearch + Logstash).
- **Modern Vue 3 UI:** Built with TypeScript, Pinia, `@ui-sdk/vue`, ECharts time-series views, RBAC (`owner`, `admin`, `member`, `viewer`), dark/light mode, and mobile-responsive layouts.

## Try Live Demo in 60 Seconds

Launch a pre-seeded 10-server simulated fleet (diurnal traffic curves, burst spikes, a flapping host, uptime checks, and `/status/demo`):

```bash
cp .env.example .env
docker compose --profile demo up -d --build
```

Open `http://localhost:8080` and sign in with `demo` / `DemoPass2026!`, or view the public status page at `http://localhost:8080/status/demo`.

## Production Deployment

### Docker Compose + Caddy (Auto TLS)

```bash
cp .env.prod.example .env
# Edit .env with your domain, SECRET_KEY, DB_PASSWORD, and REDIS_PASSWORD
docker compose -f docker-compose.prod.yml up -d --build
```

Includes Caddy (auto HTTPS + built SPA), Gunicorn + Uvicorn workers for HTTP, dedicated Uvicorn WebSocket service, ingest consumer, Celery worker, single Celery Beat, TimescaleDB PG15, and password-protected Redis 7.

Optional profiles:
- Daily backups: `docker compose -f docker-compose.prod.yml --profile backups up -d`
- Multi-tenant logs: `LOG_BACKEND=loki docker compose -f docker-compose.prod.yml --profile logs up -d`

### Kubernetes (Helm)

```bash
helm upgrade --install sysroar ./deploy/helm/sysroar \
  --namespace sysroar \
  --create-namespace \
  --values my-values.yaml
```

## Installing the Rust Agent

Create a short-lived enrollment token in **Fleet -> Add Server** and run:

```bash
# Linux (systemd) and macOS (launchd)
curl -fsSL https://raw.githubusercontent.com/kbtale/sysroar/main/scripts/install.sh | \
  sudo SYSROAR_API_BASE_URL="https://monitor.example.com" \
       SYSROAR_ENROLLMENT_TOKEN="sre_xxxx.yyyy" sh
```

```powershell
# Windows (PowerShell Service)
$env:SYSROAR_API_BASE_URL="https://monitor.example.com"
$env:SYSROAR_ENROLLMENT_TOKEN="sre_xxxx.yyyy"
irm https://raw.githubusercontent.com/kbtale/sysroar/main/scripts/install.ps1 | iex
```

## Documentation

Full guides live in `docs/` (built with VitePress):

- [Installation & Demo Mode](docs/install.md)
- [Rust Agent & Open Ingestion](docs/agent.md)
- [Alerting, Maintenance & Anomalies](docs/alerting.md)
- [Uptime Checks & Public Status Pages](docs/uptime-status.md)
- [Pluggable Logs (Loki / ELK)](docs/logs.md)
- [REST & WebSocket API](docs/api.md)
- [Upgrading & Backups](docs/UPGRADING.md)
- [Changelog](CHANGELOG.md)

## Architecture

```text
Rust Agent / OTLP / Prom Remote-Write
        |  (HTTPS gzip / snappy, AgentKey auth)
        v
Caddy (TLS + SPA) -> Gunicorn/Uvicorn (HTTP) & Uvicorn (WS)
        |  (XADD)
        v
Redis Streams ---> Ingest Consumer ---> TimescaleDB (Hypertable + 5m/1h CAGGs)
                                    |-> Channels Layer -> Live WebSocket UI
Celery Beat / Worker ---> Alert Engine (Hysteresis, Grouping, Digests)
                      |-> Uptime Checks (HTTP/TCP/SSL/DNS/Ping)
                      |-> Outbox Delivery (10 SSRF-Guarded Channels)
```

## Development & Testing

```bash
# Backend lint + tests
ruff check .
pytest

# Rust agent tests + clippy
cargo test --manifest-path agent/Cargo.toml
cargo clippy --manifest-path agent/Cargo.toml --all-targets -- -D warnings

# Frontend typecheck, unit tests, and Playwright E2E
npm --prefix frontend run typecheck
npm --prefix frontend test
npm --prefix frontend run test:e2e

# Docs site local preview
npm --prefix docs run docs:dev
```
