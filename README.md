# Linux Server Deployment & Monitoring Toolkit

[![CI](https://github.com/MuhammadSaeedAnwar/linux-server-monitoring-toolkit/actions/workflows/ci.yml/badge.svg)](https://github.com/MuhammadSaeedAnwar/linux-server-monitoring-toolkit/actions/workflows/ci.yml)

A self-contained toolkit for monitoring a Linux server's health, running
network diagnostics, checking service status, and deploying a small
Dockerized stack (app + PostgreSQL + Nginx) with a rollback-safe deploy
script and database backup/restore tooling.

Built as a portfolio project targeting Deployment & Maintenance Software
Engineer work: Linux/Ubuntu administration, Python, Bash, Docker,
PostgreSQL, Nginx, and networking fundamentals.

## 1. Project overview

The toolkit has two halves that work together:

1. **A Python monitoring application** (`monitoring/`) that collects
   system health metrics, runs network diagnostics, and checks service
   status, then stores results in PostgreSQL and prints them as text or
   JSON.
2. **A deployable stack** (Docker Compose: app + PostgreSQL + Nginx) with
   Bash tooling to deploy it, validate the environment first, roll back
   on a failed health check, and back up/restore the database.

You can use the Python CLI standalone on any Linux machine (`toolkit
check --system`), or run the whole thing as a monitoring stack with
`scripts/deploy.sh`.

## 2. Architecture

```
                 ┌────────────┐
   host / user → │   Nginx    │  reverse proxy, security headers, /health
                 └─────┬──────┘
                       │
                 ┌─────▼──────┐        ┌──────────────┐
                 │   app      │ ─────▶ │  PostgreSQL   │
                 │ (monitor   │ writes │  (checks,     │
                 │  loop)     │        │   alerts)     │
                 └────────────┘        └──────────────┘
```

- `app` is a Python container that loops: run all checks → evaluate
  alerts → write everything to Postgres → sleep → repeat.
- `nginx` is the single externally-facing service. It doesn't proxy to
  an HTTP API today (the monitor is a background loop, not a web
  server) — it's a working, documented reverse-proxy baseline with
  security headers and a `/health` endpoint that `deploy.sh` uses to
  verify the stack came up correctly.
- `db` is plain PostgreSQL 15, with schema managed by `sql/init.sql`
  (idempotent `CREATE TABLE IF NOT EXISTS`).

### Python package layout

```
monitoring/
├── cli.py            # argparse CLI: check / init-db / alerts
├── config.py          # loads config.yaml (non-secret) + .env (secrets)
├── logger.py           # text or JSON structured logging
├── models.py            # typed dataclasses (SystemHealth, ServiceCheck, ...)
├── alerts.py             # turns check results into AlertEvent objects
├── db.py                  # PostgreSQL storage layer (parameterized SQL only)
└── collectors/
    ├── system.py           # CPU / RAM / disk / uptime / load average
    ├── network.py           # DNS / ping / TCP port / HTTP / traceroute
    └── services.py           # systemctl-based service status
```

Each collector is independent and unit-tested in isolation; the CLI just
wires them together. This is deliberate: it's the same shape you'd want
if this grew into a real monitoring agent (Prometheus exporter, etc.)
later.

## 3. Technologies

| Concern            | Choice                          | Why |
|---------------------|----------------------------------|-----|
| Language             | Python 3.12 + Bash               | Python for structured logic/testing, Bash for orchestration where it's simplest |
| System metrics        | `psutil`                        | Cross-platform, well-maintained, avoids hand-parsing `/proc` |
| Database                | PostgreSQL 15                 | Common production choice; JSONB column used for warning lists |
| DB driver                 | `psycopg2-binary`            | Standard, mature Postgres driver |
| Containerization             | Docker + Docker Compose  | Reproducible local environment, matches how this would realistically ship |
| Reverse proxy                  | Nginx                  | Industry-standard; used here for headers + health endpoint |
| Config                            | YAML + `.env`         | Non-secret settings versioned in git; secrets never are |
| Testing                              | `pytest` + mocking  | Fast, no real network/DB required for unit tests |

## 4. Features

- **System health**: CPU%, memory%, disk%, uptime, 1/5/15-minute load
  average, with configurable warning thresholds per metric.
- **Network diagnostics**: DNS resolution, ICMP ping (with parsed
  latency), TCP port connectivity, HTTP/HTTPS health checks with
  expected-status matching, and traceroute — each with a clear,
  specific error message when it fails.
- **Service monitoring**: `systemctl is-active` checks for configured
  services, correctly distinguishing active / inactive / failed /
  "systemd not available" (e.g. inside a plain container).
- **Deployment automation**: `scripts/deploy.sh` validates the
  environment, builds and starts the stack, polls a health endpoint,
  and rolls back to the previous app image if the health check fails.
- **Storage**: every check result and every alert is written to
  PostgreSQL with a timestamp, queryable later.
- **Backups**: `scripts/backup_db.sh` produces a timestamped, gzipped
  `pg_dump`; `scripts/restore_db.sh` restores one with a confirmation
  prompt.

## 5. Installation (Ubuntu)

Tested against Ubuntu 22.04/24.04.

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip docker.io docker-compose-plugin \
    iputils-ping traceroute postgresql-client

git clone https://github.com/MuhammadSaeedAnwar/linux-server-monitoring-toolkit.git linux-toolkit
cd linux-toolkit

python3 -m venv .venv
source .venv/bin/activate
pip install ".[dev]

cp .env.example .env
# edit .env: set a real POSTGRES_PASSWORD at minimum
```

Running the monitor without Docker (against a locally installed
PostgreSQL, or just to see system/network checks with no DB at all):

```bash
python -m monitoring.cli check --all
python -m monitoring.cli check --system --json
python -m monitoring.cli check --network
```

## 6. Docker setup

```bash
cp .env.example .env      # if you haven't already
# edit .env and set a real POSTGRES_PASSWORD

chmod +x scripts/*.sh
./scripts/deploy.sh
```

`deploy.sh` will:
1. Run `scripts/env_check.sh` (fails fast if `.env` is missing/incomplete
   or Docker isn't installed).
2. Tag the currently-running app image as `linux-toolkit-app:previous`
   (for rollback).
3. Build and start `db`, `app`, and `nginx` via Docker Compose.
4. Poll `http://localhost:8080/health` for up to 30 seconds.
5. Roll back to the previous app image automatically if the health
   check never succeeds.

Check it worked:
```bash
curl http://localhost:8080/health
docker compose logs -f app
```

## 7. Configuration

- `config/config.yaml` — thresholds, which services/hosts/URLs to check.
  Safe to commit; contains no secrets.
- `.env` (from `.env.example`) — PostgreSQL credentials, monitor
  interval, log level, Nginx host port. **Never commit this file** (it's
  in `.gitignore`).

To monitor different services or hosts, edit the `services:` and
`network_checks:` sections of `config/config.yaml` — no code changes
needed.

## 8. Deployment

Covered in section 6. For a from-scratch redeploy:

```bash
docker compose down -v   # -v also drops the pgdata volume — be sure
./scripts/deploy.sh
```

For a config-only change (no image rebuild needed), edit
`config/config.yaml` and restart just the app container:
```bash
docker compose restart app
```

## 9. Monitoring examples

Run all checks and store to PostgreSQL:
```bash
python -m monitoring.cli check --all --store
```

Only network diagnostics, JSON output (useful for piping into another
tool):
```bash
python -m monitoring.cli check --network --json
```

View recent alerts (requires `.env` DB settings and `init-db` already
having run):
```bash
python -m monitoring.cli alerts --limit 10
```

Example output (`check --system --json`):
```json
{
  "system": {
    "cpu_percent": 12.3,
    "memory_percent": 41.7,
    "disk_percent": 58.0,
    "load_average_1m": 0.42,
    "status": "ok",
    "warnings": []
  },
  "alert_count": 0
}
```

## 10. Troubleshooting guide

| Symptom | Likely cause | Fix |
|---|---|---|
| `Configuration error: Missing required environment variables` | `.env` missing or incomplete | `cp .env.example .env` and fill it in |
| `psycopg2.OperationalError: could not connect to server` | Postgres not up yet, or wrong `POSTGRES_HOST` | Wait for `db` healthcheck; if running the CLI outside Docker, set `POSTGRES_HOST=localhost` in `.env` |
| Service checks all return `status: unknown` | Running inside a container/host without systemd as PID 1 | Expected — run the check on a real systemd host (or via SSH to one) to get real results |
| `ping`/`traceroute` checks return `status: unknown` | Binaries not installed | `sudo apt install iputils-ping traceroute` (already included in `docker/app.Dockerfile`) |
| `deploy.sh` rolls back immediately | App/Nginx failed to start, or `/health` unreachable | `docker compose logs app nginx`, check `NGINX_HOST_PORT` isn't already in use |
| `env_check.sh` fails on placeholder password | You haven't edited `.env` yet | Set a real `POSTGRES_PASSWORD` |

## 11. Security considerations

- **No secrets in code or in `config.yaml`.** All credentials come from
  `.env`, which is git-ignored; `.env.example` documents required keys
  with placeholder values.
- **No hardcoded SSH keys, no offensive tooling.** This toolkit only
  observes and reports; it has no exploit or attack functionality.
- **Parameterized SQL only.** Every query in `db.py` uses `%s`
  placeholders through `psycopg2`, never string formatting, to prevent
  SQL injection.
- **Subprocess calls use fixed argument lists**, never `shell=True` and
  never string-built shell commands, avoiding shell injection in the
  ping/traceroute collectors.
- **Least privilege in Docker.** The app container runs as a non-root
  user (`toolkit`, uid 1000), not root.
- **Nginx security headers** (`X-Frame-Options`, `X-Content-Type-Options`,
  `Content-Security-Policy`, etc.) are set by default; `server_tokens
  off` hides the Nginx version.
- **SSH is out of scope for automation on purpose.** This project does
  not include any script that SSHes into remote hosts or manages SSH
  keys — that's a meaningfully larger trust boundary (remote code
  execution) than a portfolio project should casually add. In a real
  deployment, you'd run this toolkit's CLI *on* the target host (via
  cron/systemd timer, or the Docker stack), or trigger it from a CI/CD
  pipeline that already has vetted SSH access, rather than have the
  toolkit itself hold SSH credentials.
- **Backups are not encrypted at rest** by this project — if you need
  that, encrypt the `backups/` directory or the storage it lives on
  separately; that's called out here rather than silently assumed.

## 12. Testing

```bash
pip install ".[dev]
pytest tests/ -v
```

28 unit tests cover:
- System collector threshold logic (OK vs. warning states, missing
  `getloadavg` on non-POSIX systems).
- Network collector success/failure paths for DNS, ping, TCP, and HTTP
  (external calls are mocked — tests don't require real network access).
- Alert generation (alerts fire only for warning/critical/error states).
- Config loading (valid config, missing file, invalid YAML, missing
  thresholds).
- Database layer (correct SQL is issued, connection lifecycle is
  correct) — all with a mocked `psycopg2.connect`, so tests don't
  require a real PostgreSQL instance.

There's intentionally no integration test that spins up real Docker
containers in CI here — see Limitations below.

## 13. Failure and recovery validation

The deployed stack was tested by intentionally stopping PostgreSQL while the monitoring application remained running, waiting for the monitoring cycle to detect the failed TCP connection, then restarting PostgreSQL and verifying service recovery and the `/health` endpoint.

This validates the operational workflow end to end: **failure → detection → recovery → healthy stack**.

## 13. Project limitations

Being upfront about scope, since this is a portfolio project built by
one person, not a production system with an on-call rotation behind it:

- **No integration test suite against real Docker/Postgres.** Unit
  tests mock the database and network calls; there's no CI job that
  actually spins up `docker compose` and hits a live stack end-to-end.
- **Alerting has no dedupe or escalation.** Every unhealthy check
  produces an alert row every cycle — there's no "only alert once until
  resolved" logic or paging integration.
- **Nginx doesn't proxy to a real HTTP API.** The monitor is a
  background loop, not a web service, so Nginx here demonstrates the
  reverse-proxy + security-header + health-check pattern rather than
  fronting real application traffic.
- **Rollback is single-host and image-tag based**, not a zero-downtime
  blue/green or canary deploy.
- **No SSH-based remote deployment automation** (see Security section
  for why that's a deliberate scope cut, not an oversight).
- **Traceroute output parsing is minimal** (hop count only); it doesn't
  extract per-hop latency.

## 15. Screenshots / demo instructions

No screenshots are included in this repository since the primary
interface is a CLI and JSON output, not a GUI. To demo it live:

```bash
# Terminal 1: bring up the stack
./scripts/deploy.sh

# Terminal 2: watch it work
curl -s http://localhost:8080/health
docker compose logs -f app
python -m monitoring.cli alerts --limit 5
```

For a recorded demo, `asciinema rec demo.cast` while running the
sequence above captures a terminal recording without needing any GUI.

## License

MIT — use this however is useful to you.
