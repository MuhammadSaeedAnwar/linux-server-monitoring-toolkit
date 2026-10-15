"""Regression tests for the CLI (P1 fixes).

All collectors and the database are replaced with fakes: no real
network, systemd or PostgreSQL is touched.
"""

import json
import logging
from datetime import datetime, timezone
from unittest.mock import MagicMock

import psycopg2
import pytest

from monitoring import cli
from monitoring.models import NetworkCheckResult, ServiceCheck, Status, SystemHealth

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)

CONFIG_YAML = """
thresholds:
  cpu_percent_warning: 80
services: [ssh]
network_checks: {}
logging:
  level: info
"""


def _health(warnings=None):
    warnings = warnings or []
    return SystemHealth(
        timestamp=NOW, cpu_percent=12.5, memory_percent=40.0, disk_percent=50.0,
        uptime_seconds=93784, load_average_1m=0.42, load_average_5m=0.35, load_average_15m=0.3,
        status=Status.WARNING if warnings else Status.OK, warnings=warnings,
    )


def _service(status=Status.OK):
    return ServiceCheck(name="ssh", running=status == Status.OK, status=status, detail="active", timestamp=NOW)


def _net(status=Status.OK):
    return NetworkCheckResult(
        check_type="dns", target="example.com", success=status == Status.OK, status=status,
        detail="resolved", latency_ms=3.2, timestamp=NOW,
    )


@pytest.fixture
def fakes(monkeypatch):
    """Replace the three collectors with fakes and record which ran."""
    calls = {"system": 0, "services": 0, "network": 0, "thresholds": None}
    state = {"health": _health(), "service": _service(), "net": _net()}

    class FakeSystem:
        def __init__(self, thresholds):
            calls["thresholds"] = thresholds

        def collect(self):
            calls["system"] += 1
            return state["health"]

    class FakeServices:
        def __init__(self, names):
            pass

        def run_all(self):
            calls["services"] += 1
            return [state["service"]]

    class FakeNetwork:
        def __init__(self, cfg):
            pass

        def run_all(self):
            calls["network"] += 1
            return [state["net"]]

    monkeypatch.setattr(cli, "SystemCollector", FakeSystem)
    monkeypatch.setattr(cli, "ServiceCollector", FakeServices)
    monkeypatch.setattr(cli, "NetworkCollector", FakeNetwork)
    return calls, state


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(CONFIG_YAML)
    return path


@pytest.fixture
def db_env(monkeypatch):
    for key, value in {
        "POSTGRES_HOST": "127.0.0.1", "POSTGRES_PORT": "5432", "POSTGRES_DB": "toolkit",
        "POSTGRES_USER": "u", "POSTGRES_PASSWORD": "super-secret-pw",
    }.items():
        monkeypatch.setenv(key, value)


def _fake_db(monkeypatch, connect_exc=None, insert_exc=None):
    db = MagicMock()
    if connect_exc is not None:
        db.connect.side_effect = connect_exc
    if insert_exc is not None:
        db.insert_system_health.side_effect = insert_exc
    monkeypatch.setattr(cli, "Database", MagicMock(return_value=db))
    return db


# --- 1. bare `check` runs all collectors -----------------------------------

def test_bare_check_runs_all_collectors(fakes, config_file, capsys):
    calls, _ = fakes
    rc = cli.main(["--config", str(config_file), "check", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert {"system", "services", "network"} <= out.keys()
    assert calls["system"] == calls["services"] == calls["network"] == 1


def test_single_flag_runs_only_that_collector(fakes, config_file, capsys):
    calls, _ = fakes
    cli.main(["--config", str(config_file), "check", "--network", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert "network" in out and "system" not in out and "services" not in out
    assert calls["system"] == 0 and calls["services"] == 0


def test_help_text_still_documents_all_as_default(capsys):
    with pytest.raises(SystemExit):
        cli.main(["check", "--help"])
    assert "default if none specified" in capsys.readouterr().out


# --- 2. text output vs JSON -------------------------------------------------

def test_text_output_is_human_readable_not_json(fakes, config_file, capsys):
    rc = cli.main(["--config", str(config_file), "check"])
    out = capsys.readouterr().out
    assert rc == 0
    with pytest.raises(json.JSONDecodeError):
        json.loads(out)
    assert "System   [OK      ]" in out
    assert "CPU 12.5%" in out and "Uptime 1d 2h 3m" in out
    assert "Services" in out and "ssh" in out
    assert "Network" in out and "example.com" in out and "3.2 ms" in out
    assert "Alerts raised: 0" in out


def test_text_output_shows_warnings(fakes, config_file, capsys):
    _, state = fakes
    state["health"] = _health(["CPU usage 95% exceeds 80%"])
    rc = cli.main(["--config", str(config_file), "check", "--system"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "[WARNING ]" in out and "! CPU usage 95% exceeds 80%" in out
    assert "Alerts raised: 1" in out


def test_json_stdout_stays_valid_when_errors_are_logged(fakes, config_file, db_env, monkeypatch, capsys):
    _fake_db(monkeypatch, connect_exc=psycopg2.OperationalError("connection refused"))
    cli.main(["--config", str(config_file), "check", "--store", "--json"])
    captured = capsys.readouterr()
    json.loads(captured.out)  # must not raise
    assert "connection refused" in captured.err
    assert "connection refused" not in captured.out


# --- 3. PostgreSQL failures -------------------------------------------------

def test_db_connect_failure_prints_results_and_exits_3(fakes, config_file, db_env, monkeypatch, capsys):
    calls, _ = fakes
    _fake_db(monkeypatch, connect_exc=psycopg2.OperationalError("could not connect to server"))
    rc = cli.main(["--config", str(config_file), "check", "--store", "--json"])
    captured = capsys.readouterr()
    out = json.loads(captured.out)
    assert rc == cli.EXIT_DB_ERROR == 3
    assert {"system", "services", "network"} <= out.keys()
    assert out["storage"] == "failed (see error log)"
    assert calls["network"] == 1
    assert "Traceback" not in captured.err + captured.out
    assert "Cannot connect to PostgreSQL" in captured.err
    assert "super-secret-pw" not in captured.err + captured.out


def test_db_write_failure_mid_run_keeps_checking_and_exits_3(fakes, config_file, db_env, monkeypatch, capsys):
    calls, _ = fakes
    db = _fake_db(monkeypatch, insert_exc=psycopg2.InterfaceError("connection already closed"))
    rc = cli.main(["--config", str(config_file), "check", "--store"])
    captured = capsys.readouterr()
    assert rc == 3
    assert calls["services"] == 1 and calls["network"] == 1
    assert "Network" in captured.out and "Storage: failed" in captured.out
    assert "Failed to store results" in captured.err
    assert "Traceback" not in captured.err
    # storage switched off after the first failure
    db.insert_service_check.assert_not_called()
    db.insert_network_check.assert_not_called()
    db.close.assert_called()


def test_db_error_overrides_critical_exit_code(fakes, config_file, db_env, monkeypatch, capsys):
    _, state = fakes
    state["net"] = _net(Status.CRITICAL)
    _fake_db(monkeypatch, connect_exc=psycopg2.OperationalError("down"))
    assert cli.main(["--config", str(config_file), "check", "--store", "--json"]) == 3


def test_successful_store_reports_stored(fakes, config_file, db_env, monkeypatch, capsys):
    db = _fake_db(monkeypatch)
    rc = cli.main(["--config", str(config_file), "check", "--store", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["storage"] == "stored"
    db.insert_system_health.assert_called_once()
    db.insert_network_check.assert_called_once()


def test_store_without_db_settings_is_config_error(fakes, config_file, capsys):
    rc = cli.main(["--config", str(config_file), "check", "--store"])
    assert rc == 2
    assert "Missing required environment variables" in capsys.readouterr().err


def test_no_store_flag_has_no_storage_field(fakes, config_file, capsys):
    cli.main(["--config", str(config_file), "check", "--json"])
    assert "storage" not in json.loads(capsys.readouterr().out)


@pytest.mark.parametrize("command", [["init-db"], ["alerts"]])
def test_db_commands_exit_3_without_traceback(command, config_file, db_env, monkeypatch, capsys):
    _fake_db(monkeypatch, connect_exc=psycopg2.OperationalError("could not connect to server"))
    # Database is used as a context manager by these commands.
    cli.Database.return_value.__enter__.side_effect = psycopg2.OperationalError("could not connect")
    rc = cli.main(["--config", str(config_file), *command])
    captured = capsys.readouterr()
    assert rc == 3
    assert "Traceback" not in captured.err
    assert "could not connect" in captured.err


def test_alerts_text_and_json_output(config_file, db_env, monkeypatch, capsys):
    db = _fake_db(monkeypatch)
    rows = [{"id": 1, "raised_at": NOW, "source": "network", "message": "dns failed", "severity": "critical"}]
    db.__enter__.return_value.recent_alerts.return_value = rows

    assert cli.main(["--config", str(config_file), "alerts"]) == 0
    text = capsys.readouterr().out
    assert "2026-01-01T00:00:00+00:00  [CRITICAL] network: dns failed" in text

    assert cli.main(["--config", str(config_file), "alerts", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["message"] == "dns failed"


def test_alerts_text_when_empty(config_file, db_env, monkeypatch, capsys):
    db = _fake_db(monkeypatch)
    db.__enter__.return_value.recent_alerts.return_value = []
    cli.main(["--config", str(config_file), "alerts"])
    assert "No alerts stored." in capsys.readouterr().out


# --- 4. TOOLKIT_CONFIG_PATH and LOG_LEVEL ---------------------------------

def _custom_config(tmp_path, cpu=42, level="info"):
    path = tmp_path / "custom.yaml"
    path.write_text(f"thresholds:\n  cpu_percent_warning: {cpu}\nlogging:\n  level: {level}\n")
    return path


def test_toolkit_config_path_env_is_used(fakes, tmp_path, monkeypatch, capsys):
    calls, _ = fakes
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TOOLKIT_CONFIG_PATH", str(_custom_config(tmp_path, cpu=42)))
    assert cli.main(["check", "--system", "--json"]) == 0
    assert calls["thresholds"] == {"cpu_percent_warning": 42}


def test_config_flag_beats_env(fakes, tmp_path, monkeypatch, capsys):
    calls, _ = fakes
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TOOLKIT_CONFIG_PATH", str(_custom_config(tmp_path, cpu=42)))
    flag_cfg = tmp_path / "flag.yaml"
    flag_cfg.write_text("thresholds:\n  cpu_percent_warning: 7\n")
    cli.main(["--config", str(flag_cfg), "check", "--system", "--json"])
    assert calls["thresholds"] == {"cpu_percent_warning": 7}


def test_toolkit_config_path_missing_file_is_an_error(fakes, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TOOLKIT_CONFIG_PATH", str(tmp_path / "nope.yaml"))
    assert cli.main(["check"]) == 2
    err = capsys.readouterr().err
    assert "TOOLKIT_CONFIG_PATH" in err and "nope.yaml" in err


def test_dotenv_file_sets_config_path_and_log_level(fakes, tmp_path, monkeypatch, capsys):
    calls, _ = fakes
    # load_dotenv writes os.environ directly; make sure monkeypatch undoes it.
    monkeypatch.setenv("TOOLKIT_CONFIG_PATH", "placeholder")
    monkeypatch.setenv("LOG_LEVEL", "placeholder")
    monkeypatch.delenv("TOOLKIT_CONFIG_PATH")
    monkeypatch.delenv("LOG_LEVEL")
    monkeypatch.chdir(tmp_path)
    _custom_config(tmp_path, cpu=55)
    (tmp_path / ".env").write_text("TOOLKIT_CONFIG_PATH=custom.yaml\nLOG_LEVEL=debug\n")
    assert cli.main(["check", "--system", "--json"]) == 0
    assert calls["thresholds"] == {"cpu_percent_warning": 55}
    assert logging.getLogger("toolkit").level == logging.DEBUG


def test_log_level_env_overrides_config(fakes, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LOG_LEVEL", "ERROR")
    cli.main(["--config", str(_custom_config(tmp_path, level="debug")), "check", "--system", "--json"])
    assert logging.getLogger("toolkit").level == logging.ERROR


def test_log_level_from_config_when_env_unset(fakes, tmp_path, capsys):
    cli.main(["--config", str(_custom_config(tmp_path, level="warning")), "check", "--system", "--json"])
    assert logging.getLogger("toolkit").level == logging.WARNING


def test_log_level_default_is_info(fakes, tmp_path, capsys):
    cfg = tmp_path / "nolog.yaml"
    cfg.write_text("thresholds: {}\n")
    cli.main(["--config", str(cfg), "check", "--system", "--json"])
    assert logging.getLogger("toolkit").level == logging.INFO


def test_invalid_log_level_falls_back_to_info_with_warning(fakes, config_file, monkeypatch, capsys):
    monkeypatch.setenv("LOG_LEVEL", "loud")
    rc = cli.main(["--config", str(config_file), "check", "--system", "--json"])
    captured = capsys.readouterr()
    assert rc == 0
    assert logging.getLogger("toolkit").level == logging.INFO
    assert "Invalid log level 'loud'" in captured.err
    json.loads(captured.out)


# --- 5. works outside the repository root -----------------------------------

def test_check_works_outside_repo_using_packaged_config(fakes, tmp_path, monkeypatch, capsys):
    calls, _ = fakes
    monkeypatch.chdir(tmp_path)  # no config/ directory here
    assert cli.main(["check", "--system", "--json"]) == 0
    # thresholds came from the packaged default config
    assert calls["thresholds"]["cpu_percent_warning"] == 80


def test_local_config_dir_preferred_over_packaged(fakes, tmp_path, monkeypatch, capsys):
    calls, _ = fakes
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.yaml").write_text("thresholds:\n  cpu_percent_warning: 33\n")
    cli.main(["check", "--system", "--json"])
    assert calls["thresholds"] == {"cpu_percent_warning": 33}
