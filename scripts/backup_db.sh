#!/usr/bin/env bash
# Backs up the PostgreSQL database to a timestamped, gzip-compressed
# .sql file. Works whether Postgres is running via docker-compose or
# natively on the host, since it just needs pg_dump and the .env
# connection details.
set -euo pipefail

if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

: "${POSTGRES_HOST:?POSTGRES_HOST not set (check your .env)}"
: "${POSTGRES_PORT:?POSTGRES_PORT not set}"
: "${POSTGRES_DB:?POSTGRES_DB not set}"
: "${POSTGRES_USER:?POSTGRES_USER not set}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD not set}"

BACKUP_DIR="${BACKUP_DIR:-./backups}"
mkdir -p "$BACKUP_DIR"

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_FILE="${BACKUP_DIR}/${POSTGRES_DB}_${TIMESTAMP}.sql.gz"

echo "[backup] Dumping ${POSTGRES_DB} from ${POSTGRES_HOST}:${POSTGRES_PORT}..."
PGPASSWORD="$POSTGRES_PASSWORD" pg_dump \
    --host="$POSTGRES_HOST" \
    --port="$POSTGRES_PORT" \
    --username="$POSTGRES_USER" \
    --dbname="$POSTGRES_DB" \
    --no-owner \
    --no-privileges \
    | gzip > "$OUT_FILE"

echo "[backup] Wrote $OUT_FILE ($(du -h "$OUT_FILE" | cut -f1))"
echo "[backup] To restore: scripts/restore_db.sh $OUT_FILE"
