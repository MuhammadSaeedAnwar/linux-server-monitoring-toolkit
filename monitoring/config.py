"""Configuration loading.

Non-secret settings (thresholds, which services/hosts to check) live in a
YAML file. Secrets (DB credentials) come from environment variables / a
.env file, loaded via python-dotenv. The two are never mixed: config.yaml
is safe to commit, .env never is.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:  # importlib.resources.abc is 3.11+; only needed for type hints
    from importlib.resources.abc import Traversable

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv is a required dep, but degrade gracefully
    load_dotenv = None


class ConfigError(Exception):
    """Raised when configuration is missing or invalid."""


CONFIG_ENV_VAR = "TOOLKIT_CONFIG_PATH"
LOG_LEVEL_ENV_VAR = "LOG_LEVEL"
LOCAL_CONFIG_PATH = Path("config") / "config.yaml"
DEFAULT_LOG_LEVEL = "info"
VALID_LOG_LEVELS = ("debug", "info", "warning", "error", "critical")


def load_env_file(path: str | Path = ".env") -> bool:
    """Load a .env file from the current directory if one exists.

    Variables already set in the real environment win (python-dotenv's
    default), matching how Docker Compose treats .env files.
    """
    env_path = Path(path)
    if load_dotenv is None or not env_path.is_file():
        return False
    load_dotenv(env_path, override=False)
    return True


def packaged_default_config() -> Traversable:
    """The default config shipped inside the installed package."""
    return resources.files("monitoring") / "data" / "default_config.yaml"


def resolve_config_path(cli_path: str | Path | None = None) -> tuple[Path | Traversable, str]:
    """Decide which config file to use and say where the choice came from.

    Order: --config flag, then $TOOLKIT_CONFIG_PATH, then ./config/config.yaml
    (repo checkout), then the default bundled with the package. An explicit
    path that doesn't exist is an error rather than a silent fallback.
    """
    if cli_path:
        return Path(cli_path), "--config"
    env_path = os.getenv(CONFIG_ENV_VAR, "").strip()
    if env_path:
        return Path(env_path), CONFIG_ENV_VAR
    if LOCAL_CONFIG_PATH.is_file():
        return LOCAL_CONFIG_PATH, "local config/config.yaml"
    return packaged_default_config(), "packaged default"


def resolve_log_level(config_logging: dict[str, Any] | None = None) -> tuple[str, str | None]:
    """Return (level, warning). $LOG_LEVEL beats config.yaml, default is info.

    An unrecognised value falls back to info and returns a warning message
    so the caller can log it once logging is set up.
    """
    raw = os.getenv(LOG_LEVEL_ENV_VAR, "").strip()
    source = LOG_LEVEL_ENV_VAR
    if not raw:
        raw = str((config_logging or {}).get("level") or "").strip()
        source = "config.yaml logging.level"
    if not raw:
        return DEFAULT_LOG_LEVEL, None
    level = raw.lower()
    if level not in VALID_LOG_LEVELS:
        return DEFAULT_LOG_LEVEL, (
            f"Invalid log level {raw!r} from {source}; using '{DEFAULT_LOG_LEVEL}'. "
            f"Valid values: {', '.join(VALID_LOG_LEVELS)}"
        )
    return level, None


@dataclass
class DatabaseConfig:
    host: str
    port: int
    name: str
    user: str
    password: str

    @classmethod
    def from_env(cls) -> DatabaseConfig:
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
    def load(cls, path: str | Path | Traversable, load_env: bool = True) -> AppConfig:
        if load_env:
            load_env_file()
        if isinstance(path, str):
            path = Path(path)

        if not path.is_file():
            raise ConfigError(f"Config file not found: {path}")

        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise ConfigError(f"Config file {path} must contain a YAML mapping at the top level")

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
