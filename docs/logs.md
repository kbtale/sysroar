# Pluggable Logs (Loki & ELK)

Logs are **off by default** (`LOG_BACKEND=none`) so small teams pay zero RAM or disk overhead until they want centralized logs. When `LOG_BACKEND=none`, the Logs navigation link and per-server Host Logs tab are automatically hidden.

## Option 1: Vector + Loki (`--profile logs`, Recommended)

Loki runs with `auth_enabled: true` and 7-day (`168h`) compactor retention (`deploy/loki/loki-config.yml`). Vector receives JSON log batches from the Rust agent (`:8686/logs`) and syslog over TCP (`:5140`), setting Loki's `X-Scope-OrgID` tenant header from `company_id`.

```bash
LOG_BACKEND=loki docker compose --profile logs up -d
```

Every query from Django (`telemetry/logs/loki.py`) derives `X-Scope-OrgID` strictly from `request.user.company_id`, ensuring tenants cannot read each other's logs even if they guess another server UUID.

## Option 2: Elasticsearch / Logstash (`--profile elk`)

```bash
LOG_BACKEND=elasticsearch docker compose --profile elk up -d
```

`ElasticsearchLogBackend` injects `{"term": {"company_id": "<company_id>"}}` into every search and count query.

## Log-Based Alert Rules

Create an `AlertRule` with `metric_type=log_count`, `log_level` (e.g. `ERROR`), and `log_query` (e.g. `OOMKilled`). The alert evaluator queries `LogBackend.count_matching()` over the rule window and feeds the same incident and notification pipeline.
