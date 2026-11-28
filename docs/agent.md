# Rust Agent & Open Ingestion

## One-Line Install

Generate a short-lived enrollment token from **Fleet -> Add Server** in the SysRoar UI, then run the matching installer on your host:

### Linux (systemd) & macOS (launchd)

```bash
curl -fsSL https://raw.githubusercontent.com/kbtale/sysroar/main/scripts/install.sh | \
  sudo SYSROAR_API_BASE_URL="https://monitor.example.com" \
       SYSROAR_ENROLLMENT_TOKEN="sre_xxxx.yyyy" sh
```

### Windows (PowerShell Service)

```powershell
$env:SYSROAR_API_BASE_URL="https://monitor.example.com"
$env:SYSROAR_ENROLLMENT_TOKEN="sre_xxxx.yyyy"
irm https://raw.githubusercontent.com/kbtale/sysroar/main/scripts/install.ps1 | iex
```

## Collected Metrics (Agent v0.2.0)

- **Core:** CPU usage, CPU iowait & steal, RAM & swap utilization, load average (1m), disk read/write B/s, network RX/TX B/s, uptime.
- **Diagnostics:** Top processes + total process count, per-mount disk & inode percentages, disk IOPS/utilization, temperature sensors, systemd unit states, and Docker container CPU/memory stats (when `/var/run/docker.sock` is accessible).
- **Resilience:** Samples are buffered locally in SQLite (`SYSROAR_BUFFER_PATH`), sent in gzipped batches to `/api/telemetry/ingest/batch/`, and retried with bounded exponential backoff if the server is temporarily unreachable.

## Key Environment Variables

| Variable | Description |
|---|---|
| `SYSROAR_API_BASE_URL` | Base URL of your SysRoar server |
| `SYSROAR_SERVER_ID` | Server UUID returned during enrollment |
| `SYSROAR_AGENT_KEY` | Scoped per-server agent credential (`srk_...`) |
| `SYSROAR_TELEMETRY_CADENCE` | Collection interval in seconds (5 to 3600, default 30) |
| `SYSROAR_BUFFER_PATH` | Local SQLite buffer file path |
| `SYSROAR_LOG_SHIPPER_URL` | Optional Vector HTTP endpoint (`http://vector:8686/logs`) |
| `SYSROAR_COMPANY_ID` | Company UUID required when log shipping is enabled |
| `SYSROAR_LOG_PATHS` | Comma-separated log file paths to tail |
| `SYSROAR_AUTO_UPDATE_URL` | Optional signed release manifest URL for `--check-update` |
| `SYSROAR_UPDATE_PUBKEY` | Hex-encoded Ed25519 public key for binary verification |

## Open Ingestion (OTLP/HTTP & Prometheus)

SysRoar also accepts metrics directly from OpenTelemetry Collectors and Prometheus servers using an `AgentKey` (or tenant token + `X-Server-ID` header):

### OpenTelemetry Collector (`otlphttp`)

```yaml
exporters:
  otlphttp/sysroar:
    metrics_endpoint: "https://monitor.example.com/api/telemetry/otlp/v1/metrics"
    headers:
      Authorization: "AgentKey srk_xxxx.yyyy"
```

### Prometheus (`remote_write`)

```yaml
remote_write:
  - url: "https://monitor.example.com/api/telemetry/prometheus/remote-write"
    headers:
      Authorization: "AgentKey srk_xxxx.yyyy"
```
