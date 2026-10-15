from pathlib import Path

import pytest

import monitoring.config as toolkit_config

REPO_ROOT = Path(__file__).resolve().parent.parent
REPO_DOTENV = REPO_ROOT / ".env"

_ENV_KEYS = [
    "TOOLKIT_CONFIG_PATH",
    "LOG_LEVEL",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "NGINX_HOST_PORT",
    "MONITOR_INTERVAL_SECONDS",
]


@pytest.fixture(autouse=True)
def _clean_toolkit_env(monkeypatch):
    """Keep the developer's real environment/.env from leaking into tests.

    Two problems this guards against:

    1. The CLI calls load_dotenv(".env", override=False) from the current
       directory. pytest normally runs from the repo root, so a developer's
       real .env would refill the variables deleted below (override=False
       does not help: they are unset by then). Loading that one file is
       skipped; a .env a test writes in its own tmp_path still loads.
    2. load_dotenv writes os.environ directly. monkeypatch.delenv on a key
       that is absent records nothing to undo, so values loaded during a
       test would outlive it. Setting a placeholder first makes monkeypatch
       track every key and remove it again at teardown.
    """
    for key in _ENV_KEYS:
        monkeypatch.setenv(key, "placeholder")
        monkeypatch.delenv(key)

    real_load_dotenv = toolkit_config.load_dotenv
    if real_load_dotenv is None:
        return

    def _load_dotenv_except_repo_root(dotenv_path=None, *args, **kwargs):
        if dotenv_path is not None and Path(dotenv_path).resolve() == REPO_DOTENV:
            return False
        return real_load_dotenv(dotenv_path, *args, **kwargs)

    monkeypatch.setattr(toolkit_config, "load_dotenv", _load_dotenv_except_repo_root)
