-- Schema for the Linux Server Deployment & Monitoring Toolkit.
-- Idempotent: safe to run on every startup (CREATE TABLE IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS system_health_checks (
    id              SERIAL PRIMARY KEY,
    checked_at      TIMESTAMPTZ NOT NULL,
    cpu_percent     REAL NOT NULL,
    memory_percent  REAL NOT NULL,
    disk_percent    REAL NOT NULL,
    uptime_seconds  DOUBLE PRECISION NOT NULL,
    load_avg_1m     REAL NOT NULL,
    load_avg_5m     REAL NOT NULL,
    load_avg_15m    REAL NOT NULL,
    status          TEXT NOT NULL,
    warnings        JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE TABLE IF NOT EXISTS service_checks (
    id          SERIAL PRIMARY KEY,
    checked_at  TIMESTAMPTZ NOT NULL,
    name        TEXT NOT NULL,
    running     BOOLEAN NOT NULL,
    status      TEXT NOT NULL,
    detail      TEXT
);

CREATE TABLE IF NOT EXISTS network_checks (
    id          SERIAL PRIMARY KEY,
    checked_at  TIMESTAMPTZ NOT NULL,
    check_type  TEXT NOT NULL,   -- dns | ping | tcp_port | http | traceroute
    target      TEXT NOT NULL,
    success     BOOLEAN NOT NULL,
    status      TEXT NOT NULL,
    detail      TEXT,
    latency_ms  REAL
);

CREATE TABLE IF NOT EXISTS alerts (
    id         SERIAL PRIMARY KEY,
    raised_at  TIMESTAMPTZ NOT NULL,
    source     TEXT NOT NULL,   -- system | service | network
    message    TEXT NOT NULL,
    severity   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_system_health_checked_at ON system_health_checks (checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_service_checks_checked_at ON service_checks (checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_network_checks_checked_at ON network_checks (checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_raised_at ON alerts (raised_at DESC);
