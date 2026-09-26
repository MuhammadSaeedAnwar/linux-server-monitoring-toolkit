#!/usr/bin/env bash
# Deploys the full stack (db, app, nginx) via Docker Compose.
#
# Rollback-safe approach used here, honestly scoped for this project:
# before building the new app image, the currently-running app image
# (if any) is tagged "linux-toolkit-app:previous". After bringing the
# new stack up, we poll nginx's /health endpoint. If it doesn't come
# back healthy within the timeout, we roll back by restarting the
# "previous" image instead of leaving the deploy half-broken. This is
# a single-host rollback, not a zero-downtime blue/green deploy.
set -euo pipefail

PROJECT_NAME="linux-toolkit"
APP_IMAGE="${PROJECT_NAME}-app"
HEALTH_URL="http://localhost:${NGINX_HOST_PORT:-8080}/health"
HEALTH_RETRIES=15
HEALTH_DELAY=2

log() { echo "[deploy] $*"; }

compose() {
    if docker compose version >/dev/null 2>&1; then
        docker compose "$@"
    else
        docker-compose "$@"
    fi
}

log "Step 1/5: Validating environment"
./scripts/env_check.sh

log "Step 2/5: Tagging current app image as rollback target (if it exists)"
if docker image inspect "${APP_IMAGE}:latest" >/dev/null 2>&1; then
    docker tag "${APP_IMAGE}:latest" "${APP_IMAGE}:previous"
    log "Tagged existing image as ${APP_IMAGE}:previous"
else
    log "No existing image found, this looks like a first deploy"
fi

log "Step 3/5: Building and starting services"
compose --env-file .env build
compose --env-file .env up -d

log "Step 4/5: Waiting for database and application startup"
sleep 5

log "Step 5/5: Running post-deploy health check against ${HEALTH_URL}"
healthy=0
for i in $(seq 1 "$HEALTH_RETRIES"); do
    if curl --fail --silent --max-time 3 "$HEALTH_URL" >/dev/null 2>&1; then
        healthy=1
        break
    fi
    log "Health check attempt $i/$HEALTH_RETRIES failed, retrying in ${HEALTH_DELAY}s..."
    sleep "$HEALTH_DELAY"
done

if [ "$healthy" -eq 1 ]; then
    log "Deployment successful. Stack is healthy at ${HEALTH_URL}"
    exit 0
fi

log "Health check FAILED after ${HEALTH_RETRIES} attempts."
if docker image inspect "${APP_IMAGE}:previous" >/dev/null 2>&1; then
    log "Rolling back to previous app image..."
    docker tag "${APP_IMAGE}:previous" "${APP_IMAGE}:latest"
    compose --env-file .env up -d --no-deps app
    log "Rollback complete. Investigate logs with: docker compose logs app"
else
    log "No previous image available to roll back to. Manual investigation required."
fi
exit 1
