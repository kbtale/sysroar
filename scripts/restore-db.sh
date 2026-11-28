#!/bin/sh
set -eu

if [ "$#" -lt 1 ]; then
    echo "Usage: $0 <path-to-dump-file>" >&2
    exit 1
fi

DUMP_FILE="$1"
PGHOST="${PGHOST:-db}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-sysroar_user}"
PGDATABASE="${PGDATABASE:-sysroar}"

if [ ! -f "$DUMP_FILE" ]; then
    echo "Backup file not found: ${DUMP_FILE}" >&2
    exit 1
fi

if [ -f "${DUMP_FILE}.sha256" ]; then
    sha256sum -c "${DUMP_FILE}.sha256"
fi

psql \
    --host="$PGHOST" \
    --port="$PGPORT" \
    --username="$PGUSER" \
    --dbname="$PGDATABASE" \
    --set=ON_ERROR_STOP=1 \
    -c "CREATE EXTENSION IF NOT EXISTS timescaledb; SELECT timescaledb_pre_restore();"

pg_restore \
    --host="$PGHOST" \
    --port="$PGPORT" \
    --username="$PGUSER" \
    --dbname="$PGDATABASE" \
    --clean \
    --if-exists \
    --no-owner \
    --no-privileges \
    "$DUMP_FILE"

psql \
    --host="$PGHOST" \
    --port="$PGPORT" \
    --username="$PGUSER" \
    --dbname="$PGDATABASE" \
    --set=ON_ERROR_STOP=1 \
    -c "SELECT timescaledb_post_restore();"

echo "Restored backup: ${DUMP_FILE}"
