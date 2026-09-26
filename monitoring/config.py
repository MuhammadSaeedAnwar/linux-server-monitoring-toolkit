"""Configuration loading.

Non-secret settings (thresholds, which services/hosts to check) live in a
YAML file. Secrets (DB credentials) come from environment variables / a
.env file, loaded via python-dotenv. The two are never mixed: config.yaml
is safe to commit, .env never is.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv is a required dep, but degrade gracefully
    load_dotenv = None


class ConfigError(Exception):
    """Raised when configuration is missing or invalid."""


@dataclass
class DatabaseConfig:
    host: str
    port: int
    name: str
    user: str
    password: str

    @classmethod
    def from_env(cls) -> "DatabaseConfig":
        required = ["POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"]
        missing = [key for key in required if not os.getenv(key)]
        if missing:
            raise ConfigError(
                f"Missing required environment variables: {', '.join(missing)}. "
                "Copy .env.example to .env and fill in real values."
            )
        return cls(
            host=os.environ["POSTGRES_HOST"],
            port=int(os.environ["POSTGRES_PORT"]),
            name=os.environ["POSTGRES_DB"],
            user=os.environ["POSTGRES_USER"],
            password=os.environ["POSTGRES_PASSWORD"],
        )


@dataclass
class AppConfig:
    """Top-level application configuration."""

    thresholds: dict[str, float] = field(default_factory=dict)
    services: list[str] = field(default_factory=list)
    network_checks: dict[str, Any] = field(default_factory=dict)
    logging: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path, load_env: bool = True) -> "AppConfig":
        path = Path(path)
        if load_env and load_dotenv is not None:
            env_path = Path(".env")
            if env_path.exists():
                load_dotenv(env_path)

        if not path.exists():
            raise ConfigError(f"Config file not found: {path}")

        try:
            with path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc

        return cls(
            thresholds=data.get("thresholds", {}),
            services=data.get("services", []),
            network_checks=data.get("network_checks", {}),
            logging=data.get("logging", {}),
            raw=data,
        )

    def threshold(self, key: str, default: float | None = None) -> float:
        if key not in self.thresholds:
            if default is not None:
                return default
            raise ConfigError(f"Missing required threshold: {key}")
        return float(self.thresholds[key])
