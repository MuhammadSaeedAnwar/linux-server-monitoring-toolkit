"""Command-line interface for the monitoring toolkit.

Usage examples:
    toolkit check                  # all collectors, text output
    toolkit check --system
    toolkit check --network --json
    toolkit check --all --store    # also persist to PostgreSQL

Exit codes:
    0  all checks OK
    1  at least one warning
    2  at least one critical result, or a configuration error
    3  database/storage error (results are still printed)
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from monitoring import alerts
from monitoring.collectors.network import NetworkCollector
from monitoring.collectors.services import ServiceCollector
from monitoring.collectors.system import SystemCollector
from monitoring.config import (
    AppConfig,
    ConfigError,
    DatabaseConfig,
    load_env_file,
    resolve_config_path,
    resolve_log_level,
)
from monitoring.db import Database, DatabaseError
from monitoring.logger import get_logger, setup_logging
from monitoring.output import format_alerts_text, format_check_text

EXIT_OK = 0
EXIT_WARNING = 1
EXIT_CRITICAL = 2
EXIT_DB_ERROR = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="toolkit",
        description="Linux server deployment & monitoring toolkit.",
    )
    parser.add_argument(
        "--config",
        default=None,
        help=(
            "Path to config.yaml. If omitted: $TOOLKIT_CONFIG_PATH, then ./config/config.yaml, "
            "then the default bundled with the package."
        ),
    )
    # --json is defined per-subcommand (below), not here, so it must come
    # after the subcommand name: e.g. "toolkit check --json".
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="Run health/network/service checks")
    check.add_argument("--all", action="store_true", help="Run all check types (default if none specified)")
    check.add_argument("--system", action="store_true", help="Run system resource checks")
    check.add_argument("--network", action="store_true", help="Run network diagnostics")
    check.add_argument("--services", action="store_true", help="Run service status checks")
    check.add_argument(
        "--store", action="store_true", help="Persist results to PostgreSQL (requires .env DB settings)"
    )
    check.add_argument("--json", action="store_true", help="Output results as JSON instead of text")

    init_db = sub.add_parser("init-db", help="Create database tables if they don't already exist")
    init_db.add_argument("--json", action="store_true", help=argparse.SUPPRESS)

    alerts_cmd = sub.add_parser("alerts", help="Show recent stored alerts")
    alerts_cmd.add_argument("--limit", type=int, default=20)
    alerts_cmd.add_argument("--json", action="store_true", help="Output results as JSON instead of text")

    return parser


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, default=str))


def _db_error_text(exc: BaseException) -> str:
    """One-line, credential-free description of a database error."""
    text = " ".join(str(exc).split())
    return text or exc.__class__.__name__


class _Store:
    """Wraps optional DB persistence so one failure doesn't abort the run.

    After the first error, storage is switched off for the rest of the run;
    the checks themselves keep going and their results are still printed.
    """

    def __init__(self, logger) -> None:
        self.logger = logger
        self.db: Database | None = None
        self.error: str | None = None

    def open(self) -> bool:
        """Connect. Returns False only for a configuration problem (missing DB settings)."""
        try:
            db_config = DatabaseConfig.from_env()
        except ConfigError as exc:
            self._fail(f"Cannot store results: {exc}")
            return False
        try:
            self.db = Database(db_config)
            self.db.connect()
        except DatabaseError as exc:
            self._fail(f"Cannot connect to PostgreSQL, results will not be stored: {_db_error_text(exc)}")
        return True

    def write(self, fn_name: str, *items) -> None:
        if self.db is None:
            return
        try:
            fn = getattr(self.db, fn_name)
            for item in items:
                fn(item)
        except DatabaseError as exc:
            self._fail(f"Failed to store results in PostgreSQL, storage disabled for this run: {_db_error_text(exc)}")

    def close(self) -> None:
        if self.db is not None:
            try:
                self.db.close()
            except DatabaseError:  # pragma: no cover - closing a dead connection
                pass
            self.db = None

    def _fail(self, message: str) -> None:
        self.logger.error(message)
        self.error = message
        self.close()


def cmd_check(args: argparse.Namespace, config: AppConfig, logger) -> int:
    nothing_selected = not (args.system or args.network or args.services)
    run_all = args.all or nothing_selected
    run_system = args.system or run_all
    run_network = args.network or run_all
    run_services = args.services or run_all

    output: dict[str, Any] = {}
    exit_code = EXIT_OK
    all_alerts: list = []

    store = _Store(logger)
    if args.store and not store.open():
        # Missing DB settings is a configuration error, not an outage.
        return EXIT_CRITICAL

    try:
        if run_system:
            collector = SystemCollector(config.thresholds)
            health = collector.collect()
            output["system"] = health.to_dict()
            health_alerts = alerts.alerts_from_system_health(health)
            all_alerts.extend(health_alerts)
            if health.warnings:
                exit_code = max(exit_code, EXIT_WARNING)
            store.write("insert_system_health", health)
            store.write("insert_alert", *health_alerts)

        if run_services:
            collector = ServiceCollector(config.services)
            checks = collector.run_all()
            output["services"] = [c.to_dict() for c in checks]
            service_alerts = alerts.alerts_from_service_checks(checks)
            all_alerts.extend(service_alerts)
            if any(c.status.value == "critical" for c in checks):
                exit_code = max(exit_code, EXIT_CRITICAL)
            store.write("insert_service_check", *checks)
            store.write("insert_alert", *service_alerts)

        if run_network:
            collector = NetworkCollector(config.network_checks)
            results = collector.run_all()
            output["network"] = [r.to_dict() for r in results]
            net_alerts = alerts.alerts_from_network_checks(results)
            all_alerts.extend(net_alerts)
            if any(r.status.value == "critical" for r in results):
                exit_code = max(exit_code, EXIT_CRITICAL)
            store.write("insert_network_check", *results)
            store.write("insert_alert", *net_alerts)
    finally:
        store.close()

    output["alert_count"] = len(all_alerts)
    if args.store:
        output["storage"] = "failed (see error log)" if store.error else "stored"
        if store.error:
            exit_code = EXIT_DB_ERROR

    if args.json:
        _print_json(output)
    else:
        print(format_check_text(output))
    return exit_code


def cmd_init_db(args: argparse.Namespace, config: AppConfig, logger) -> int:
    try:
        db_config = DatabaseConfig.from_env()
    except ConfigError as exc:
        logger.error(str(exc))
        return EXIT_CRITICAL
    try:
        with Database(db_config) as db:
            db.ensure_schema()
    except DatabaseError as exc:
        logger.error(f"Could not initialise the database schema: {_db_error_text(exc)}")
        return EXIT_DB_ERROR
    logger.info("Database schema is up to date.")
    return EXIT_OK


def cmd_alerts(args: argparse.Namespace, config: AppConfig, logger) -> int:
    try:
        db_config = DatabaseConfig.from_env()
    except ConfigError as exc:
        logger.error(str(exc))
        return EXIT_CRITICAL
    try:
        with Database(db_config) as db:
            rows = db.recent_alerts(limit=args.limit)
    except DatabaseError as exc:
        logger.error(f"Could not read alerts from PostgreSQL: {_db_error_text(exc)}")
        return EXIT_DB_ERROR
    if args.json:
        _print_json(rows)
    else:
        print(format_alerts_text(rows))
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # .env first, so TOOLKIT_CONFIG_PATH / LOG_LEVEL set there are honoured.
    load_env_file()
    config_path, config_source = resolve_config_path(args.config)
    try:
        config = AppConfig.load(config_path, load_env=False)
    except ConfigError as exc:
        print(f"Configuration error ({config_source}): {exc}", file=sys.stderr)
        return EXIT_CRITICAL

    level, level_warning = resolve_log_level(config.logging)
    setup_logging(
        level=level,
        json_format=bool(config.logging.get("json", False)) or args.json,
    )
    logger = get_logger()
    if level_warning:
        logger.warning(level_warning)
    logger.debug(f"Using config {config_path} ({config_source})")

    if args.command == "check":
        return cmd_check(args, config, logger)
    if args.command == "init-db":
        return cmd_init_db(args, config, logger)
    if args.command == "alerts":
        return cmd_alerts(args, config, logger)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
