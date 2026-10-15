#!/usr/bin/env bash
# Deploys the full stack (db, app, nginx) via Docker Compose.
#
# Rollback-safe approach used here, honestly scoped for this project:
# before building the new app image, the current app image (if any) is
# tagged "linux-toolkit-app:previous". The image name is fixed by the
# `image:` key in docker-compose.yml, so this works whatever folder the
# repo was cloned into. After bringing the new stack up, two things must
# pass before the deploy counts as successful:
#
#   1. nginx answers on /health at the host port from NGINX_HOST_PORT
#      (environment first, then .env, then 8080 -- same order as Compose).
#   2. the app container is running, has not restarted during a short
#      stability window (catches crash loops, e.g. a DB that never comes
#      up), and can run a system check and read from PostgreSQL inside the
#      container.
#
# If either fails we roll back by restarting the "previous" app image.
# This is a single-host rollback, not a zero-downtime blue/green deploy.
#
# The file can be sourced (e.g. by tests) without running a deployment;
# only direct execution calls main().
set -euo pipefail

APP_IMAGE="linux-toolkit-app"
APP_SERVICE="app"
DEFAULT_NGINX_PORT=8080
HEALTH_RETRIES="${HEALTH_RETRIES:-15}"
HEALTH_DELAY="${HEALTH_DELAY:-2}"
APP_STABLE_SECONDS="${APP_STABLE_SECONDS:-15}"

log() { echo "[deploy] $*"; }

compose() {
    if docker compose version >/dev/null 2>&1; then
        docker compose "$@"
    else
        docker-compose "$@"
    fi
}

# Print the value of KEY from an env file without executing the file.
# Handles optional surrounding quotes and trailing whitespace.
read_env_value() {
    local key="$1" file="${2:-.env}" line value
    [ -f "$file" ] || return 0
    line="$(grep -E "^[[:space:]]*(export[[:space:]]+)?${key}=" "$file" | tail -n 1 || true)"
    [ -n "$line" ] || return 0
    value="${line#*=}"
    value="${value%"${value##*[![:space:]]}"}"   # rtrim
    value="${value#\"}"; value="${value%\"}"
    value="${value#\'}"; value="${value%\'}"
    printf '%s' "$value"
}

# NGINX_HOST_PORT from the environment, else .env, else the default.
resolve_nginx_port() {
    local port="${NGINX_HOST_PORT:-}"
    if [ -z "$port" ]; then
        port="$(read_env_value NGINX_HOST_PORT "${1:-.env}")"
    fi
    port="${port:-$DEFAULT_NGINX_PORT}"
    if ! [[ "$port" =~ ^[0-9]+$ ]] || [ "$port" -lt 1 ] || [ "$port" -gt 65535 ]; then
        echo "[deploy] Invalid NGINX_HOST_PORT: '${port}'" >&2
        return 1
    fi
    printf '%s' "$port"
}

nginx_healthy() {
    curl --fail --silent --max-time 3 "$1" >/dev/null 2>&1
}

wait_for_nginx() {
    local url="$1" i
    for i in $(seq 1 "$HEALTH_RETRIES"); do
        if nginx_healthy "$url"; then
            return 0
        fi
        log "nginx health check attempt $i/$HEALTH_RETRIES failed, retrying in ${HEALTH_DELAY}s..."
        sleep "$HEALTH_DELAY"
    done
    return 1
}

# Prints "<status> <restart_count>" for the app container, or nothing.
app_state() {
    local cid
    cid="$(compose ps -q "$APP_SERVICE" 2>/dev/null | head -n 1 || true)"
    [ -n "$cid" ] || return 1
    docker inspect -f '{{.State.Status}} {{.RestartCount}}' "$cid" 2>/dev/null
}

app_healthy() {
    local before after status restarts rc
    if ! before="$(app_state)"; then
        log "App check: no running '${APP_SERVICE}' container found."
        return 1
    fi
    read -r status restarts <<<"$before"
    if [ "$status" != "running" ]; then
        log "App check: container status is '${status}', expected 'running'."
        return 1
    fi

    log "App check: watching for restarts for ${APP_STABLE_SECONDS}s..."
    sleep "$APP_STABLE_SECONDS"
    if ! after="$(app_state)"; then
        log "App check: container disappeared during the stability window."
        return 1
    fi
    read -r status rc <<<"$after"
    if [ "$status" != "running" ] || [ "$rc" != "$restarts" ]; then
        log "App check: container is crash-looping (status '${status}', restarts ${restarts} -> ${rc})."
        return 1
    fi

    # Exit 0 (ok) or 1 (warnings) both mean the code and config load fine.
    rc=0
    compose exec -T "$APP_SERVICE" python -m monitoring.cli check --system --json >/dev/null 2>&1 || rc=$?
    if [ "$rc" -gt 1 ]; then
        log "App check: in-container system check failed (exit ${rc})."
        return 1
    fi

    # Read-only query: proves the app can reach PostgreSQL with its credentials.
    if ! compose exec -T "$APP_SERVICE" python -m monitoring.cli alerts --limit 1 --json >/dev/null 2>&1; then
        log "App check: app cannot query PostgreSQL."
        return 1
    fi
    return 0
}

rollback() {
    if ! docker image inspect "${APP_IMAGE}:previous" >/dev/null 2>&1; then
        log "No previous image available. Manual investigation required."
        return 1
    fi
    log "Rolling back to previous app image..."
    if ! docker tag "${APP_IMAGE}:previous" "${APP_IMAGE}:latest"; then
        log "ROLLBACK FAILED: could not restore the previous image tag."
        return 1
    fi
    if ! compose --env-file .env up -d --no-deps "$APP_SERVICE"; then
        log "ROLLBACK FAILED: could not recreate the app container."
        return 1
    fi
    log "Rollback commands succeeded. Investigate logs with: docker compose logs ${APP_SERVICE}"
}

main() {
    cd "$(dirname "${BASH_SOURCE[0]}")/.."

    local port health_url
    port="$(resolve_nginx_port .env)"
    health_url="http://localhost:${port}/health"

    log "Step 1/5: Validating environment"
    bash ./scripts/env_check.sh

    log "Step 2/5: Tagging current app image as rollback target (if it exists)"
    if docker image inspect "${APP_IMAGE}:latest" >/dev/null 2>&1; then
        docker tag "${APP_IMAGE}:latest" "${APP_IMAGE}:previous"
        log "Tagged existing image as ${APP_IMAGE}:previous"
    else
        log "No existing image found, this looks like a first deploy"
    fi

    log "Step 3/5: Building and starting services"
    if ! compose --env-file .env build; then
        log "Image build FAILED."
        rollback || log "Rollback failed or no previous image exists. Manual investigation required."
        exit 1
    fi

    if ! compose --env-file .env up -d; then
        log "Service startup FAILED."
        rollback || log "Rollback failed or no previous image exists. Manual investigation required."
        exit 1
    fi

    log "Step 4/5: Waiting for nginx at ${health_url}"
    if ! wait_for_nginx "$health_url"; then
        log "nginx health check FAILED after ${HEALTH_RETRIES} attempts."
        rollback
        exit 1
    fi

    log "Step 5/5: Checking the app container"
    if ! app_healthy; then
        log "App health check FAILED."
        rollback
        exit 1
    fi

    log "Deployment successful. nginx is up at ${health_url} and the app is healthy."
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
