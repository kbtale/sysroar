# REST & WebSocket API

Interactive Swagger documentation is available at `/api/docs/` and the OpenAPI 3.0 schema is served at `/api/schema/` (and tracked in `docs/openapi.yaml`).

## Authentication Schemes

| Scheme | Header / Cookie | Intended Use |
|---|---|---|
| Browser Session | HttpOnly session cookie + `X-CSRFToken` | Vue SPA (CSRF + Axes lockout protected) |
| Agent Key | `Authorization: AgentKey <prefix.secret>` | Rust agent, OTLP/HTTP, Prometheus remote-write (ingest/config/inventory only) |
| Tenant Token | `Authorization: Token <key>` | Automation and API integrations |
| WebSocket Ticket | `?ticket=<one-time-token>` | Real-time `/ws/telemetry/` and `/ws/logs/` connections |

## Tenant Isolation Invariants

- Every tenant-scoped endpoint derives `company_id` exclusively from the authenticated user or `AgentKey` record. Client-supplied tenant IDs are ignored.
- Cross-tenant resource lookups return `404 Not Found` (or `400`/`403` on foreign-key references).
- Role-based permissions (`viewer`, `member`, `admin`, `owner`) are enforced server-side on every mutating endpoint.

## Core Endpoints

- **Auth & Setup:** `/api/accounts/setup/`, `/api/accounts/auth/login/`, `/api/accounts/auth/me/`, `/api/accounts/auth/ticket/`, `/api/accounts/members/`, `/api/accounts/invites/`
- **Fleet & Monitoring:** `/api/monitoring/servers/`, `/api/monitoring/uptime-checks/`, `/api/monitoring/rules/`, `/api/monitoring/channels/`, `/api/monitoring/incidents/`, `/api/monitoring/silences/`, `/api/monitoring/maintenance-windows/`, `/api/monitoring/status-pages/`, `/api/monitoring/audit-logs/`
- **Telemetry & Open Ingestion:** `/api/telemetry/enroll/`, `/api/telemetry/ingest/batch/`, `/api/telemetry/otlp/v1/metrics`, `/api/telemetry/prometheus/remote-write`, `/api/telemetry/servers/<id>/metrics/`
- **Logs:** `/api/logs/status/`, `/api/logs/query/`, `ws/logs/`
- **Public & Ops:** `/api/public/status/<slug>/`, `/healthz`, `/readyz`, `/metrics`
