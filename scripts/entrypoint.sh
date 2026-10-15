#!/usr/bin/env bash
# Entrypoint for the app container: waits for postgres, ensures schema,
# then runs the check loop forever at MONITOR_INTERVAL_SECONDS.
set -euo pipefail

INTERVAL="${MONITOR_INTERVAL_SECONDS:-60}"

echo "[entrypoint] Waiting for database at ${POSTGRES_HOST}:${POSTGRES_PORT}..."
for i in $(seq 1 30); do
    if python -c "
import os, socket, sys
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(2)
try:
    s.connect((os.environ['POSTGRES_HOST'], int(os.environ['POSTGRES_PORT'])))
    sys.exit(0)
except OSError:
    sys.exit(1)
"; then
        echo "[entrypoint] Database is reachable."
        break
    fi
    echo "[entrypoint] Database not ready yet (attempt $i/30)..."
    sleep 2
done

echo "[entrypoint] Ensuring schema exists..."
python -m monitoring.cli init-db

echo "[entrypoint] Starting monitoring loop (every ${INTERVAL}s). Ctrl+C to stop."
while true; do
    python -m monitoring.cli check --all --store || echo "[entrypoint] Check cycle reported warnings/errors (see output above)."
    sleep "$INTERVAL"
done
