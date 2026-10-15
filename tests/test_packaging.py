"""Package resources must be usable from an installed copy, not just the repo."""

import importlib.util
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from monitoring.config import packaged_default_config, resolve_config_path
from monitoring.db import schema_sql

REPO = Path(__file__).resolve().parents[1]


def test_schema_is_available_as_package_resource():
    sql = schema_sql()
    assert "CREATE TABLE IF NOT EXISTS alerts" in sql


def test_packaged_default_config_matches_repo_config():
    # Guards against the two copies drifting apart.
    packaged = packaged_default_config().read_text(encoding="utf-8")
    assert packaged == (REPO / "config" / "config.yaml").read_text(encoding="utf-8")


def test_resolve_config_path_order(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert resolve_config_path(None)[1] == "packaged default"
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.yaml").write_text("{}")
    assert resolve_config_path(None)[1] == "local config/config.yaml"
    monkeypatch.setenv("TOOLKIT_CONFIG_PATH", "x.yaml")
    assert resolve_config_path(None) == (Path("x.yaml"), "TOOLKIT_CONFIG_PATH")
    assert resolve_config_path("y.yaml") == (Path("y.yaml"), "--config")


@pytest.mark.skipif(
    importlib.util.find_spec("setuptools") is None or importlib.util.find_spec("pip") is None,
    reason="needs pip and setuptools to build a wheel",
)
def test_built_wheel_contains_schema_and_default_config(tmp_path):
    build_dir = tmp_path / "src"
    shutil.copytree(REPO, build_dir, ignore=shutil.ignore_patterns(".git", ".venv", "*.egg-info", "build", "dist"))
    subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation", "-q", "-w", str(tmp_path / "dist"), str(build_dir)],
        check=True,
    )
    wheel = next((tmp_path / "dist").glob("*.whl"))
    names = zipfile.ZipFile(wheel).namelist()
    assert "monitoring/sql/init.sql" in names
    assert "monitoring/data/default_config.yaml" in names
