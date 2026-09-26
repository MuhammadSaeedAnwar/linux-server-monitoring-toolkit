#!/usr/bin/env bash
# Validates the local environment before a deployment is attempted.
# Exits non-zero on the first hard failure so deploy.sh can bail out
# early instead of half-deploying.
set -euo pipefail

fail() {
    echo "[env_check] FAIL: $1" >&2
    exit 1
}

ok() {
    echo "[env_check] OK: $1"
}

command -v docker >/dev/null 2>&1 || fail "docker is not installed or not on PATH"
ok "docker found ($(docker --version))"

if docker compose version >/dev/null 2>&1; then
    ok "docker compose plugin found"
elif command -v docker-compose >/dev/null 2>&1; then
    ok "docker-compose (standalone) found"
else
    fail "neither 'docker compose' nor 'docker-compose' is available"
fi

[ -f .env ] || fail ".env file not found. Copy .env.example to .env and fill in real values."
ok ".env file present"

# Every variable listed in .env.example must actually be set in .env.
missing=0
while IFS='=' read -r key _; do
    [[ "$key" =~ ^#.*$ || -z "$key" ]] && continue
    if ! grep -q "^${key}=" .env; then
        echo "[env_check] Missing key in .env: ${key}" >&2
        missing=1
    fi
done < .env.example

if [ "$missing" -ne 0 ]; then
    fail "one or more required variables are missing from .env (see above)"
fi
ok "all required .env keys are present"

# Refuse to deploy with the example placeholder password.
if grep -q "POSTGRES_PASSWORD=change_me_before_running" .env; then
    fail "POSTGRES_PASSWORD is still the placeholder value. Set a real password in .env."
fi
ok "POSTGRES_PASSWORD has been changed from the placeholder"

[ -f config/config.yaml ] || fail "config/config.yaml not found"
ok "config/config.yaml present"

echo "[env_check] Environment validation passed."
