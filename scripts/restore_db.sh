#!/usr/bin/env bash
# Restores a PostgreSQL backup produced by backup_db.sh.
#
# Usage: scripts/restore_db.sh backups/toolkit_20260101T000000Z.sql.gz
set -euo pipefail

if [ $# -ne 1 ]; then
    echo "Usage: $0 <path-to-backup.sql.gz>" >&2
    exit 1
fi

BACKUP_FILE="$1"
[ -f "$BACKUP_FILE" ] || { echo "Backup file not found: $BACKUP_FILE" >&2; exit 1; }

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

echo "WARNING: this will restore into database '${POSTGRES_DB}' on ${POSTGRES_HOST}:${POSTGRES_PORT}."
read -r -p "Type 'yes' to continue: " confirm
[ "$confirm" = "yes" ] || { echo "Aborted."; exit 1; }

echo "[restore] Restoring from $BACKUP_FILE..."
gunzip -c "$BACKUP_FILE" | PGPASSWORD="$POSTGRES_PASSWORD" psql \
    --host="$POSTGRES_HOST" \
    --port="$POSTGRES_PORT" \
    --username="$POSTGRES_USER" \
    --dbname="$POSTGRES_DB"

echo "[restore] Restore complete."
