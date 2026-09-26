import os

import pytest

from monitoring.config import AppConfig, ConfigError, DatabaseConfig


def test_load_valid_config(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
thresholds:
  cpu_percent_warning: 75
services:
  - nginx
network_checks:
  dns:
    hostnames: ["example.com"]
logging:
  level: debug
"""
    )
    config = AppConfig.load(config_file, load_env=False)
    assert config.threshold("cpu_percent_warning") == 75
    assert config.services == ["nginx"]
    assert config.logging["level"] == "debug"


def test_load_missing_file_raises(tmp_path):
    with pytest.raises(ConfigError):
        AppConfig.load(tmp_path / "does_not_exist.yaml", load_env=False)


def test_load_invalid_yaml_raises(tmp_path):
    bad_file = tmp_path / "bad.yaml"
    bad_file.write_text("thresholds: [unclosed")
    with pytest.raises(ConfigError):
        AppConfig.load(bad_file, load_env=False)


def test_threshold_missing_without_default_raises():
    config = AppConfig(thresholds={})
    with pytest.raises(ConfigError):
        config.threshold("does_not_exist")


def test_threshold_missing_with_default_returns_default():
    config = AppConfig(thresholds={})
    assert config.threshold("does_not_exist", default=42) == 42


def test_database_config_from_env_success(monkeypatch):
    monkeypatch.setenv("POSTGRES_HOST", "db")
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    monkeypatch.setenv("POSTGRES_DB", "toolkit")
    monkeypatch.setenv("POSTGRES_USER", "user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret")

    db_config = DatabaseConfig.from_env()
    assert db_config.host == "db"
    assert db_config.port == 5432


def test_database_config_from_env_missing_raises(monkeypatch):
    for key in ["POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"]:
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ConfigError):
        DatabaseConfig.from_env()
