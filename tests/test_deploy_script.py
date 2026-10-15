"""Regression tests for scripts/deploy.sh.

`docker` and `curl` are replaced with stub scripts on PATH, so nothing is
built, started, deployed or rolled back. The stubs only print what they
were asked to do.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
DEPLOY = REPO / "scripts" / "deploy.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")

DOCKER_STUB = r"""#!/usr/bin/env bash
echo "docker $*" >> "$STUB_LOG"
case "$1" in
  --version) echo "Docker version stub"; exit 0 ;;
  tag) exit 0 ;;
  image) exit "${STUB_IMAGE_RC:-0}" ;;
  inspect)
    n=$(( $(cat "$STUB_DIR/inspect_count" 2>/dev/null || echo 0) + 1 ))
    echo "$n" > "$STUB_DIR/inspect_count"
    line=$(sed -n "${n}p" "$STUB_DIR/states")
    [ -n "$line" ] || line=$(tail -n 1 "$STUB_DIR/states")
    echo "$line"; exit 0 ;;
  compose)
    shift
    while [ "${1:-}" = "--env-file" ]; do shift 2; done
    case "${1:-}" in
      version) exit 0 ;;
      ps) echo "${STUB_CID-abc123}"; exit 0 ;;
      exec)
        case "$*" in
          *" alerts "*) exit "${STUB_ALERTS_RC:-0}" ;;
          *" check "*) exit "${STUB_CHECK_RC:-0}" ;;
        esac
        exit 0 ;;
      *) exit 0 ;;
    esac ;;
esac
exit 0
"""

CURL_STUB = r"""#!/usr/bin/env bash
echo "curl $*" >> "$STUB_LOG"
exit "${STUB_CURL_RC:-0}"
"""


@pytest.fixture
def stub_env(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in {"docker": DOCKER_STUB, "curl": CURL_STUB}.items():
        path = bin_dir / name
        path.write_text(body)
        path.chmod(0o755)
    (tmp_path / "states").write_text("running 0\n")
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "STUB_LOG": str(tmp_path / "calls.log"),
        "STUB_DIR": str(tmp_path),
        "APP_STABLE_SECONDS": "0",
        "HEALTH_RETRIES": "2",
        "HEALTH_DELAY": "0",
        "HOME": str(tmp_path),
    }
    return tmp_path, env


def _source_and_run(snippet, env, cwd):
    script = f'source "{DEPLOY}"\n{snippet}'
    return subprocess.run(["bash", "-c", script], env=env, cwd=cwd, capture_output=True, text=True, check=False)


def _calls(tmp_path):
    log = tmp_path / "calls.log"
    return log.read_text() if log.exists() else ""


# --- port handling ---------------------------------------------------------

def test_port_read_from_dotenv_when_not_in_environment(stub_env):
    tmp, env = stub_env
    (tmp / ".env").write_text("POSTGRES_DB=x\nNGINX_HOST_PORT=9091\n")
    result = _source_and_run("resolve_nginx_port .env", env, tmp)
    assert result.returncode == 0 and result.stdout == "9091"


def test_environment_port_beats_dotenv(stub_env):
    tmp, env = stub_env
    (tmp / ".env").write_text("NGINX_HOST_PORT=9091\n")
    result = _source_and_run("resolve_nginx_port .env", {**env, "NGINX_HOST_PORT": "7070"}, tmp)
    assert result.stdout == "7070"


@pytest.mark.parametrize("line", ['NGINX_HOST_PORT="9092"', "NGINX_HOST_PORT='9092'", "NGINX_HOST_PORT=9092   ",
                                  "export NGINX_HOST_PORT=9092"])
def test_port_parsing_handles_quotes_and_whitespace(stub_env, line):
    tmp, env = stub_env
    (tmp / ".env").write_text(line + "\n")
    assert _source_and_run("resolve_nginx_port .env", env, tmp).stdout == "9092"


def test_port_defaults_to_8080(stub_env):
    tmp, env = stub_env
    assert _source_and_run("resolve_nginx_port .env", env, tmp).stdout == "8080"


@pytest.mark.parametrize("bad", ["abc", "0", "70000"])
def test_invalid_port_is_rejected(stub_env, bad):
    tmp, env = stub_env
    (tmp / ".env").write_text(f"NGINX_HOST_PORT={bad}\n")
    result = _source_and_run("resolve_nginx_port .env", env, tmp)
    assert result.returncode != 0 and "Invalid NGINX_HOST_PORT" in result.stderr


def test_dotenv_is_parsed_not_executed(stub_env):
    tmp, env = stub_env
    (tmp / ".env").write_text("NGINX_HOST_PORT=8081\n$(touch pwned)\ntouch pwned2\n")
    result = _source_and_run("resolve_nginx_port .env", env, tmp)
    assert result.stdout == "8081"
    assert not (tmp / "pwned").exists() and not (tmp / "pwned2").exists()


# --- image naming -----------------------------------------------------------

def test_image_name_in_script_matches_compose():
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text())
    assert compose["services"]["app"]["image"] == "linux-toolkit-app:latest"
    assert 'APP_IMAGE="linux-toolkit-app"' in DEPLOY.read_text()
    # A Compose project `name:` would rename the pgdata volume for existing installs.
    assert "name" not in compose


# --- app health -------------------------------------------------------------

def test_app_healthy_passes_for_stable_running_app(stub_env):
    tmp, env = stub_env
    result = _source_and_run("app_healthy", env, tmp)
    assert result.returncode == 0, result.stdout + result.stderr
    calls = _calls(tmp)
    assert "exec -T app python -m monitoring.cli check --system --json" in calls
    assert "exec -T app python -m monitoring.cli alerts --limit 1 --json" in calls


def test_app_healthy_accepts_warning_exit_code(stub_env):
    tmp, env = stub_env
    assert _source_and_run("app_healthy", {**env, "STUB_CHECK_RC": "1"}, tmp).returncode == 0


def test_app_healthy_detects_crash_loop(stub_env):
    tmp, env = stub_env
    (tmp / "states").write_text("running 0\nrunning 2\n")
    result = _source_and_run("app_healthy", env, tmp)
    assert result.returncode != 0 and "crash-looping" in result.stdout


def test_app_healthy_detects_restarting_container(stub_env):
    tmp, env = stub_env
    (tmp / "states").write_text("restarting 3\n")
    result = _source_and_run("app_healthy", env, tmp)
    assert result.returncode != 0 and "'restarting'" in result.stdout


def test_app_healthy_detects_missing_container(stub_env):
    tmp, env = stub_env
    result = _source_and_run("app_healthy", {**env, "STUB_CID": ""}, tmp)
    assert result.returncode != 0 and "no running 'app' container" in result.stdout


def test_app_healthy_detects_database_unreachable(stub_env):
    tmp, env = stub_env
    result = _source_and_run("app_healthy", {**env, "STUB_ALERTS_RC": "3"}, tmp)
    assert result.returncode != 0 and "cannot query PostgreSQL" in result.stdout


def test_app_healthy_detects_broken_check(stub_env):
    tmp, env = stub_env
    result = _source_and_run("app_healthy", {**env, "STUB_CHECK_RC": "2"}, tmp)
    assert result.returncode != 0 and "system check failed" in result.stdout


def test_sourcing_does_not_deploy(stub_env):
    tmp, env = stub_env
    result = _source_and_run("true", env, tmp)
    assert result.returncode == 0
    assert _calls(tmp) == ""


# --- simulated full run (stubs only, nothing is deployed) -------------------

def _project_copy(tmp):
    proj = tmp / "proj"
    (proj / "scripts").mkdir(parents=True)
    (proj / "config").mkdir()
    for name in ("deploy.sh", "env_check.sh"):
        shutil.copy(REPO / "scripts" / name, proj / "scripts" / name)
    shutil.copy(REPO / ".env.example", proj / ".env.example")
    shutil.copy(REPO / "config" / "config.yaml", proj / "config" / "config.yaml")
    env_text = (REPO / ".env.example").read_text()
    env_text = env_text.replace("change_me_before_running", "a-real-password").replace(
        "NGINX_HOST_PORT=8080", "NGINX_HOST_PORT=9099"
    )
    (proj / ".env").write_text(env_text)
    return proj


def test_simulated_deploy_rolls_back_when_app_crash_loops_but_nginx_is_up(stub_env):
    tmp, env = stub_env
    proj = _project_copy(tmp)
    (tmp / "states").write_text("running 0\nrestarting 1\n")
    result = subprocess.run(["bash", str(proj / "scripts" / "deploy.sh")], env=env, capture_output=True, text=True, check=False)
    calls = _calls(tmp)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "App health check FAILED" in result.stdout
    assert "curl --fail --silent --max-time 3 http://localhost:9099/health" in calls
    assert "docker tag linux-toolkit-app:previous linux-toolkit-app:latest" in calls
    assert "up -d --no-deps app" in calls


def test_simulated_deploy_succeeds_when_nginx_and_app_are_healthy(stub_env):
    tmp, env = stub_env
    proj = _project_copy(tmp)
    result = subprocess.run(["bash", str(proj / "scripts" / "deploy.sh")], env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Deployment successful" in result.stdout
    assert "docker tag linux-toolkit-app:latest linux-toolkit-app:previous" in _calls(tmp)
    assert "linux-toolkit-app:previous linux-toolkit-app:latest" not in _calls(tmp)


def test_simulated_deploy_rolls_back_when_nginx_down(stub_env):
    tmp, env = stub_env
    proj = _project_copy(tmp)
    result = subprocess.run(
        ["bash", str(proj / "scripts" / "deploy.sh")],
        env={**env, "STUB_CURL_RC": "7"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "nginx health check FAILED" in result.stdout
    assert "docker tag linux-toolkit-app:previous linux-toolkit-app:latest" in _calls(tmp)
