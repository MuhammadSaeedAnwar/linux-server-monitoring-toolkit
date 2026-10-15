#!/usr/bin/env bash
set -euo pipefail

if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

: "${POSTGRES_DB:?POSTGRES_DB not set (check your .env)}"
: "${POSTGRES_USER:?POSTGRES_USER not set}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD not set}"

POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"

mkdir -p "$BACKUP_DIR"

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_FILE="${BACKUP_DIR}/${POSTGRES_DB}_${TIMESTAMP}.sql.gz"

if docker compose ps --status running db 2>/dev/null | grep -q "db"; then
    echo "[backup] Dumping ${POSTGRES_DB} from Docker Compose database..."

    docker compose exec -T db \
        pg_dump \
        --username="$POSTGRES_USER" \
        --dbname="$POSTGRES_DB" \
        --no-owner \
        --no-privileges \
        | gzip > "$OUT_FILE"
else
    echo "[backup] Docker Compose database not running."
    echo "[backup] Dumping ${POSTGRES_DB} from ${POSTGRES_HOST}:${POSTGRES_PORT}..."

    PGPASSWORD="$POSTGRES_PASSWORD" pg_dump \
        --host="$POSTGRES_HOST" \
        --port="$POSTGRES_PORT" \
        --username="$POSTGRES_USER" \
        --dbname="$POSTGRES_DB" \
        --no-owner \
        --no-privileges \
        | gzip > "$OUT_FILE"
fi

echo "[backup] Wrote $OUT_FILE ($(du -h "$OUT_FILE" | cut -f1))"
echo "[backup] To restore: scripts/restore_db.sh $OUT_FILE"
