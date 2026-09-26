#!/usr/bin/env bash
set -euo pipefail

if [ $# -ne 1 ]; then
    echo "Usage: $0 <path-to-backup.sql.gz>" >&2
    exit 1
fi

BACKUP_FILE="$1"

if [ ! -f "$BACKUP_FILE" ]; then
    echo "Backup file not found: $BACKUP_FILE" >&2
    exit 1
fi

if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

: "${POSTGRES_DB:?POSTGRES_DB not set (check your .env)}"
: "${POSTGRES_USER:?POSTGRES_USER not set}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD not set}"

echo "WARNING: this will restore into database '${POSTGRES_DB}'."
read -r -p "Type 'yes' to continue: " confirm

if [ "$confirm" != "yes" ]; then
    echo "Aborted."
    exit 1
fi

if docker compose ps --status running db 2>/dev/null | grep -q "db"; then
    echo "[restore] Restoring into Docker Compose database..."

    gunzip -c "$BACKUP_FILE" | docker compose exec -T db \
        psql \
        --username="$POSTGRES_USER" \
        --dbname="$POSTGRES_DB"
else
    POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
    POSTGRES_PORT="${POSTGRES_PORT:-5432}"

    echo "[restore] Docker Compose database not running."
    echo "[restore] Restoring into ${POSTGRES_HOST}:${POSTGRES_PORT}..."

    gunzip -c "$BACKUP_FILE" | PGPASSWORD="$POSTGRES_PASSWORD" psql \
        --host="$POSTGRES_HOST" \
        --port="$POSTGRES_PORT" \
        --username="$POSTGRES_USER" \
        --dbname="$POSTGRES_DB"
fi

echo "[restore] Restore complete."
