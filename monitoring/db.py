"""PostgreSQL storage layer.

All queries are parameterized (never string-formatted SQL) to avoid SQL
injection. Connection details come exclusively from DatabaseConfig,
which itself only reads from environment variables -- credentials never
appear in code or in config.yaml.
"""

from __future__ import annotations

import json
from typing import Any, Optional

import psycopg2
import psycopg2.extras

from monitoring.config import DatabaseConfig
from monitoring.models import AlertEvent, NetworkCheckResult, ServiceCheck, SystemHealth


class Database:
    def __init__(self, config: DatabaseConfig) -> None:
        self.config = config
        self._conn: Optional[psycopg2.extensions.connection] = None

    def connect(self) -> None:
        self._conn = psycopg2.connect(
            host=self.config.host,
            port=self.config.port,
            dbname=self.config.name,
            user=self.config.user,
            password=self.config.password,
            connect_timeout=5,
        )
        self._conn.autocommit = True

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "Database":
        self.connect()
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    @property
    def conn(self) -> psycopg2.extensions.connection:
        if self._conn is None:
            raise RuntimeError("Database is not connected. Call connect() or use as a context manager.")
        return self._conn

    def ensure_schema(self, sql_path: str = "sql/init.sql") -> None:
        with open(sql_path, "r", encoding="utf-8") as f:
            schema_sql = f.read()
        with self.conn.cursor() as cur:
            cur.execute(schema_sql)

    def insert_system_health(self, health: SystemHealth) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO system_health_checks
                    (checked_at, cpu_percent, memory_percent, disk_percent,
                     uptime_seconds, load_avg_1m, load_avg_5m, load_avg_15m,
                     status, warnings)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    health.timestamp,
                    health.cpu_percent,
                    health.memory_percent,
                    health.disk_percent,
                    health.uptime_seconds,
                    health.load_average_1m,
                    health.load_average_5m,
                    health.load_average_15m,
                    health.status.value,
                    json.dumps(health.warnings),
                ),
            )

    def insert_service_check(self, check: ServiceCheck) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO service_checks (checked_at, name, running, status, detail)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (check.timestamp, check.name, check.running, check.status.value, check.detail),
            )

    def insert_network_check(self, check: NetworkCheckResult) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO network_checks
                    (checked_at, check_type, target, success, status, detail, latency_ms)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    check.timestamp,
                    check.check_type,
                    check.target,
                    check.success,
                    check.status.value,
                    check.detail,
                    check.latency_ms,
                ),
            )

    def insert_alert(self, alert: AlertEvent) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO alerts (raised_at, source, message, severity)
                VALUES (%s, %s, %s, %s)
                """,
                (alert.timestamp, alert.source, alert.message, alert.severity.value),
            )

    def recent_alerts(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM alerts ORDER BY raised_at DESC LIMIT %s", (limit,)
            )
            return list(cur.fetchall())
