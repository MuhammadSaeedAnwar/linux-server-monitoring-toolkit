"""Command-line interface for the monitoring toolkit.

Usage examples:
    python -m monitoring.cli check --all
    python -m monitoring.cli check --system
    python -m monitoring.cli check --network --json
    python -m monitoring.cli check --services --no-store
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from typing import Any

from monitoring import alerts
from monitoring.collectors.network import NetworkCollector
from monitoring.collectors.services import ServiceCollector
from monitoring.collectors.system import SystemCollector
from monitoring.config import AppConfig, ConfigError, DatabaseConfig
from monitoring.db import Database
from monitoring.logger import get_logger, setup_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="toolkit",
        description="Linux server deployment & monitoring toolkit.",
    )
    parser.add_argument(
        "--config", default="config/config.yaml", help="Path to config.yaml (default: config/config.yaml)"
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


def _print_result(payload: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, default=str))
        return
    print(json.dumps(payload, indent=2, default=str))  # text mode still pretty-prints structured data


def cmd_check(args: argparse.Namespace, config: AppConfig, logger) -> int:
    run_system = args.system or args.all or not (args.system or args.network or args.services)
    run_network = args.network or args.all
    run_services = args.services or args.all

    output: dict[str, Any] = {}
    exit_code = 0
    db: Database | None = None
    all_alerts: list = []

    if args.store:
        try:
            db = Database(DatabaseConfig.from_env())
            db.connect()
        except ConfigError as exc:
            logger.error(f"Cannot store results: {exc}")
            return 2

    try:
        if run_system:
            collector = SystemCollector(config.thresholds)
            health = collector.collect()
            output["system"] = health.to_dict()
            health_alerts = alerts.alerts_from_system_health(health)
            all_alerts.extend(health_alerts)
            if health.warnings:
                exit_code = 1
            if db:
                db.insert_system_health(health)
                for a in health_alerts:
                    db.insert_alert(a)

        if run_services:
            collector = ServiceCollector(config.services)
            checks = collector.run_all()
            output["services"] = [c.to_dict() for c in checks]
            service_alerts = alerts.alerts_from_service_checks(checks)
            all_alerts.extend(service_alerts)
            if any(c.status.value == "critical" for c in checks):
                exit_code = 2
            if db:
                for c in checks:
                    db.insert_service_check(c)
                for a in service_alerts:
                    db.insert_alert(a)

        if run_network:
            collector = NetworkCollector(config.network_checks)
            results = collector.run_all()
            output["network"] = [r.to_dict() for r in results]
            net_alerts = alerts.alerts_from_network_checks(results)
            all_alerts.extend(net_alerts)
            if any(r.status.value == "critical" for r in results):
                exit_code = max(exit_code, 2)
            if db:
                for r in results:
                    db.insert_network_check(r)
                for a in net_alerts:
                    db.insert_alert(a)
    finally:
        if db:
            db.close()

    output["alert_count"] = len(all_alerts)
    _print_result(output, args.json)
    return exit_code


def cmd_init_db(args: argparse.Namespace, config: AppConfig, logger) -> int:
    try:
        db_config = DatabaseConfig.from_env()
    except ConfigError as exc:
        logger.error(str(exc))
        return 2
    with Database(db_config) as db:
        db.ensure_schema()
    logger.info("Database schema is up to date.")
    return 0


def cmd_alerts(args: argparse.Namespace, config: AppConfig, logger) -> int:
    try:
        db_config = DatabaseConfig.from_env()
    except ConfigError as exc:
        logger.error(str(exc))
        return 2
    with Database(db_config) as db:
        rows = db.recent_alerts(limit=args.limit)
    _print_result(rows, args.json)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        config = AppConfig.load(args.config)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    setup_logging(
        level=config.logging.get("level", "info"),
        json_format=config.logging.get("json", False) or args.json,
    )
    logger = get_logger()

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
