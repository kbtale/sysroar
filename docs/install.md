# Installation & Demo Mode

## 60-Second Demo Mode

Launch a full simulated fleet of 10 servers (realistic diurnal curves, load spikes, a flapping host, uptime checks, and a public status page) with one command:

```bash
cp .env.example .env
docker compose --profile demo up -d --build
```

Open `http://localhost:8080` and sign in with:
- **Username:** `demo`
- **Password:** `DemoPass2026!`
- **Public status page:** `http://localhost:8080/status/demo`

## Production Deployment (Docker Compose + Caddy)

The production compose file runs Caddy (automatic HTTPS + built Vue SPA), Gunicorn with Uvicorn workers for HTTP, a dedicated Uvicorn service for WebSockets, the Redis Streams ingest consumer, Celery worker, a single Celery Beat scheduler, TimescaleDB PG15, and password-protected Redis 7.

1. Create your production environment file:

```bash
cp .env.prod.example .env
```

2. Set strong unique values for `SECRET_KEY`, `DB_PASSWORD`, `REDIS_PASSWORD`, `SYSROAR_DOMAIN`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, and `FRONTEND_URL`.

3. Start the production stack:

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

4. Visit `https://your-domain` to complete the first-run setup wizard (creates the initial admin user and company workspace).

### Optional Production Profiles

- **Automated daily backups:** `docker compose -f docker-compose.prod.yml --profile backups up -d`
- **Multi-tenant logs (Vector + Loki):** set `LOG_BACKEND=loki` and run `docker compose -f docker-compose.prod.yml --profile logs up -d`

## Kubernetes (Helm)

Install SysRoar into a Kubernetes cluster using the bundled Helm chart:

```bash
helm upgrade --install sysroar ./deploy/helm/sysroar \
  --namespace sysroar \
  --create-namespace \
  --values my-values.yaml
```

The chart provisions a `pre-install,pre-upgrade` migration Job hook, `web` and `ws` Deployments with `/healthz` and `/readyz` probes, `ingest-consumer`, `celery-worker`, single-replica `celery-beat`, the static SPA frontend, Ingress with WebSocket timeouts, and an optional TimescaleDB backup CronJob.
