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
- `db` is plain PostgreSQL 15, with schema managed by
  `monitoring/sql/init.sql` (idempotent `CREATE TABLE IF NOT EXISTS`),
  applied by `toolkit init-db`.

### Python package layout

```
monitoring/
├── cli.py              # argparse CLI: check / init-db / alerts
├── config.py           # loads config.yaml (non-secret) + .env (secrets)
├── logger.py           # text or JSON structured logging (to stderr)
├── output.py           # human-readable text output
├── models.py           # typed dataclasses (SystemHealth, ServiceCheck, ...)
├── alerts.py           # turns check results into AlertEvent objects
├── db.py               # PostgreSQL storage layer (parameterized SQL only)
├── sql/init.sql        # schema, shipped inside the package
├── data/default_config.yaml  # fallback config, shipped inside the package
└── collectors/
    ├── system.py       # CPU / RAM / disk / uptime / load average
    ├── network.py      # DNS / ping / TCP port / HTTP / traceroute
    └── services.py     # systemctl-based service status
```

Each collector is independent and unit-tested in isolation; the CLI just
wires them together. This is deliberate: it's the same shape you'd want
if this grew into a real monitoring agent (Prometheus exporter, etc.)
later.

## 3. Technologies

| Concern | Choice | Why |
|---|---|---|
| Language | Python 3.10+ (3.12 in Docker) + Bash | Python for structured logic/testing, Bash for orchestration where it's simplest |
| System metrics | `psutil` | Cross-platform, well-maintained, avoids hand-parsing `/proc` |
| Database | PostgreSQL 15 | Common production choice; JSONB column used for warning lists |
| DB driver | `psycopg2-binary` | Standard, mature Postgres driver |
| Containerization | Docker + Docker Compose | Reproducible local environment, matches how this would realistically ship |
| Reverse proxy | Nginx | Industry-standard; used here for headers + health endpoint |
| Config | YAML + `.env` | Non-secret settings versioned in git; secrets never are |
| Testing | `pytest` + mocking | Fast, no real network/DB required for unit tests |

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
  environment, builds and starts the stack, checks both Nginx and the
  app container, and rolls back to the previous app image if either
  check fails.
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

git clone https://github.com/MuhammadSaeedAnwar/linux-server-monitoring-toolkit.git
cd linux-server-monitoring-toolkit

python3 -m venv .venv
source .venv/bin/activate
pip install .            # or: pip install ".[dev]" to also get the test tools

cp .env.example .env
# edit .env: set a real POSTGRES_PASSWORD at minimum
```

Running the monitor without Docker (against a locally installed
PostgreSQL, or just to see system/network checks with no DB at all):

```bash
toolkit check              # all collectors, human-readable text
toolkit check --system --json
toolkit check --network
```

The installed `toolkit` command works from any directory. The schema and
a default config ship inside the package (see Configuration). Running
`python -m monitoring.cli ...` from the repo root also works.

Note: the default `config/config.yaml` checks the Docker hostnames `db`
and `nginx`, which only resolve inside the Compose network. When running
on the host, edit those `tcp_ports` entries or expect them to report
critical.

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
2. Tag the current app image as `linux-toolkit-app:previous` (for
   rollback). The name is fixed in `docker-compose.yml`, so it doesn't
   depend on the folder you cloned into.
3. Build and start `db`, `app`, and `nginx` via Docker Compose.
4. Poll Nginx's `/health` on the port from `NGINX_HOST_PORT` (shell
   environment first, then `.env`, then 8080) for up to 30 seconds.
5. Check the app itself: the container must be running, must not
   restart during a 15-second window (catches crash loops), and must be
   able to run a system check and query PostgreSQL from inside the
   container.
6. Roll back to the previous app image automatically if step 4 or 5
   fails.

Check it worked:
```bash
curl http://localhost:8080/health
docker compose logs -f app
```

## 7. Configuration

- `config/config.yaml`: thresholds, which services/hosts/URLs to check.
  Safe to commit; contains no secrets.
- `.env` (from `.env.example`): PostgreSQL credentials, monitor
  interval, log level, config path, Nginx host port. **Never commit this
  file** (it's in `.gitignore`).

To monitor different services or hosts, edit the `services:` and
`network_checks:` sections of `config/config.yaml`. No code changes
needed.

Which config file the CLI uses, first match wins:

1. `--config PATH`
2. `TOOLKIT_CONFIG_PATH` (environment or `.env`; relative paths are
   resolved from the current directory)
3. `./config/config.yaml`, if it exists in the current directory
4. the default bundled with the package

An explicit path (1 or 2) that doesn't exist is an error, not a silent
fallback.

Log level: `LOG_LEVEL` (environment or `.env`) overrides `logging.level`
in `config.yaml`; the default is `info`. Accepted values are `debug`,
`info`, `warning`, `error` and `critical`. Anything else falls back to
`info` with a warning. Logs go to stderr, so `--json` output on stdout
stays valid JSON.

Real environment variables take precedence over values in `.env`.

## 8. Deployment

Covered in section 6. For a from-scratch redeploy:

```bash
docker compose down -v   # -v also drops the pgdata volume — be sure
./scripts/deploy.sh
```

For a config-only change (no image rebuild needed), edit
`config/config.yaml` and restart just the app container. Compose mounts
the file into the container read-only, so the restart picks up the
change:
```bash
docker compose restart app
```

## 9. Monitoring examples

Run all checks and store to PostgreSQL (`check` with no flags runs all
collectors, the same as `--all`):
```bash
toolkit check --store
```

Only network diagnostics, JSON output (useful for piping into another
tool):
```bash
toolkit check --network --json
```

View recent alerts (requires `.env` DB settings and `init-db` already
having run):
```bash
toolkit alerts --limit 10
```

Example text output (`check --system`):
```
System   [OK      ]
  CPU 12.3%   Memory 41.7%   Disk 58.0%
  Load 0.42 / 0.35 / 0.30   Uptime 3d 4h 12m

Alerts raised: 0
```

Example JSON output (`check --system --json`, abridged):
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

With `--store`, the output also has a `"storage"` field: `"stored"`, or
`"failed (see error log)"` if PostgreSQL was unreachable or a write
failed. Checks still run and print in that case.

Exit codes:

| Code | Meaning |
|---|---|
| 0 | All checks OK |
| 1 | At least one warning |
| 2 | At least one critical result, or a configuration error |
| 3 | Database error (results are still printed; no traceback) |

## 10. Troubleshooting guide

| Symptom | Likely cause | Fix |
|---|---|---|
| `Configuration error: Missing required environment variables` | `.env` missing or incomplete | `cp .env.example .env` and fill it in |
| `Cannot connect to PostgreSQL, results will not be stored` (exit code 3) | Postgres not up yet, or wrong `POSTGRES_HOST` | Wait for `db` healthcheck; if running the CLI outside Docker, set `POSTGRES_HOST=localhost` in `.env` |
| `Configuration error (TOOLKIT_CONFIG_PATH): Config file not found` | `TOOLKIT_CONFIG_PATH` points at a missing file | Fix or unset it; relative paths resolve from the current directory |
| Service checks all return `status: unknown` | Running inside a container/host without systemd as PID 1 | Expected — run the check on a real systemd host (or via SSH to one) to get real results |
| `ping`/`traceroute` checks return `status: unknown` | Binaries not installed | `sudo apt install iputils-ping traceroute` (already included in `docker/app.Dockerfile`) |
| `deploy.sh` rolls back | Nginx `/health` unreachable, or the app container crash-looped / couldn't reach PostgreSQL | `docker compose logs app nginx`; check `NGINX_HOST_PORT` isn't already in use |
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
pip install ".[dev]"
pytest tests/ -v
```

The unit tests cover:
- System collector threshold logic (OK vs. warning states, missing
  `getloadavg` on non-POSIX systems).
- Network collector success/failure paths for DNS, ping, TCP, and HTTP
  (external calls are mocked — tests don't require real network access).
- Alert generation (alerts fire only for warning/critical/error states).
- Config loading (valid config, missing file, invalid YAML, missing
  thresholds).
- Database layer (correct SQL is issued, connection lifecycle is
  correct, schema loads from the installed package), all with a mocked
  `psycopg2.connect`, so tests don't require a real PostgreSQL instance.
- CLI behaviour: default collectors, text vs. JSON output, exit code 3
  and no traceback when PostgreSQL is down, `TOOLKIT_CONFIG_PATH` and
  `LOG_LEVEL` handling, and running from outside the repo.
- `deploy.sh` helpers (port resolution, app crash-loop detection, and a
  rollback triggered by an unhealthy app), using stub `docker`/`curl`
  binaries. Nothing is actually deployed.

There's intentionally no integration test that spins up real Docker
containers in CI here — see Limitations below.

## 13. Failure and recovery validation

The deployed stack was tested by intentionally stopping PostgreSQL while the monitoring application remained running, waiting for the monitoring cycle to detect the failed TCP connection, then restarting PostgreSQL and verifying service recovery and the `/health` endpoint.

This validates the operational workflow end to end: **failure → detection → recovery → healthy stack**.

## 14. Project limitations

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

MIT. See [LICENSE](LICENSE).
