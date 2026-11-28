# Upgrading SysRoar

This guide covers safe, repeatable upgrades for Docker Compose and Kubernetes (Helm) deployments, plus backup and rollback procedures.

## Pre-Upgrade Checklist

1. Review `CHANGELOG.md` for any new required environment variables or breaking changes.
2. Take a verified TimescaleDB backup before pulling new images:

```bash
docker compose -f docker-compose.prod.yml --profile backups run --rm -e BACKUP_ONCE=true db_backup
```

3. Confirm the backup artifact and `.sha256` checksum were written to the `db_backups` volume.

## Upgrading Docker Compose (Production)

```bash
git pull origin main
docker compose -f docker-compose.prod.yml build --pull
docker compose -f docker-compose.prod.yml up -d
```

The `web` container runs `python manage.py migrate --noinput` automatically on startup via `RUN_MIGRATIONS=true`. All dependent services (`ws`, `ingest_consumer`, `celery_worker`, `celery_beat`, `caddy`) wait until `web` reports healthy at `/healthz`.

Verify health after rollout:

```bash
docker compose -f docker-compose.prod.yml ps
curl -sf https://monitor.example.com/healthz
curl -sf https://monitor.example.com/readyz
```

## Upgrading Kubernetes (Helm)

```bash
helm upgrade sysroar ./deploy/helm/sysroar \
  --namespace sysroar \
  --values my-values.yaml \
  --atomic \
  --timeout 5m
```

The chart runs a `pre-upgrade` Job hook (`migration-job.yaml`) that applies Django migrations before rolling the `web`, `ws`, and worker Deployments. With `--atomic`, Helm rolls back automatically if the migration Job or Deployment probes fail.

## Restoring a Backup

Stop application writers before restoring so no active transactions conflict with `timescaledb_pre_restore()`:

```bash
docker compose -f docker-compose.prod.yml stop web ws ingest_consumer celery_worker celery_beat
docker compose -f docker-compose.prod.yml run --rm --no-deps \
  -v "$(pwd)/scripts/restore-db.sh:/usr/local/bin/restore-db.sh:ro" \
  db_backup sh -c "sed 's/\r$//' /usr/local/bin/restore-db.sh > /tmp/restore-db.sh && sh /tmp/restore-db.sh /backups/sysroar-YYYYMMDDTHHMMSSZ.dump"
docker compose -f docker-compose.prod.yml up -d
```

## Upgrading Rust Agents

- **Signed auto-update:** Run `sysroar-agent --check-update` (or enable a systemd timer / cron job) with `SYSROAR_AUTO_UPDATE_URL` and `SYSROAR_UPDATE_PUBKEY`. The agent verifies both the SHA-256 digest and Ed25519 signature before replacing the binary.
- **One-line reinstall:** Re-run `scripts/install.sh` (Linux/macOS) or `scripts/install.ps1` (Windows) with the existing `SYSROAR_API_BASE_URL` and `SYSROAR_AGENT_KEY`.
