#!/bin/sh
set -eu

BACKUP_DIR="${BACKUP_DIR:-/backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
PGHOST="${PGHOST:-db}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-sysroar_user}"
PGDATABASE="${PGDATABASE:-sysroar}"

mkdir -p "$BACKUP_DIR"

attempt=0
while ! pg_isready --host="$PGHOST" --port="$PGPORT" --username="$PGUSER" --dbname="$PGDATABASE" >/dev/null 2>&1; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 15 ]; then
        echo "Database not ready at ${PGHOST}:${PGPORT}" >&2
        exit 1
    fi
    sleep 1
done

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
TARGET_FILE="${BACKUP_DIR}/sysroar-${TIMESTAMP}.dump"
TMP_FILE="${TARGET_FILE}.tmp"

pg_dump \
    --host="$PGHOST" \
    --port="$PGPORT" \
    --username="$PGUSER" \
    --dbname="$PGDATABASE" \
    --format=custom \
    --compress=9 \
    --no-owner \
    --file="$TMP_FILE"

if [ ! -s "$TMP_FILE" ]; then
    rm -f "$TMP_FILE"
    echo "Backup file is empty" >&2
    exit 1
fi

mv "$TMP_FILE" "$TARGET_FILE"
sha256sum "$TARGET_FILE" > "${TARGET_FILE}.sha256"

find "$BACKUP_DIR" -type f -name 'sysroar-*.dump' -mtime +"$RETENTION_DAYS" -delete
find "$BACKUP_DIR" -type f -name 'sysroar-*.dump.sha256' -mtime +"$RETENTION_DAYS" -delete

echo "Created backup: ${TARGET_FILE}"
