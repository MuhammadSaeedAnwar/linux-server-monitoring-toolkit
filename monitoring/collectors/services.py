"""Service status checks via systemctl.

Targets Ubuntu/systemd, which is what the project is built for. On a
system without systemd (e.g. inside a minimal container), checks are
reported as UNKNOWN rather than crashing, so the toolkit degrades
gracefully instead of failing outright.
"""

from __future__ import annotations

import shutil
import subprocess

from monitoring.models import ServiceCheck, Status, utc_now


class ServiceCollector:
    def __init__(self, service_names: list[str]) -> None:
        self.service_names = service_names
        self._systemctl_available = shutil.which("systemctl") is not None

    def check_service(self, name: str) -> ServiceCheck:
        if not self._systemctl_available:
            return ServiceCheck(
                name=name,
                running=False,
                status=Status.UNKNOWN,
                detail="systemctl not available on this host (non-systemd system)",
                timestamp=utc_now(),
            )
        try:
            result = subprocess.run(
                ["systemctl", "is-active", name],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except subprocess.TimeoutExpired:
            return ServiceCheck(
                name=name,
                running=False,
                status=Status.ERROR,
                detail="systemctl call timed out",
                timestamp=utc_now(),
            )
        except FileNotFoundError:
            return ServiceCheck(
                name=name,
                running=False,
                status=Status.UNKNOWN,
                detail="systemctl binary disappeared mid-check",
                timestamp=utc_now(),
            )

        state = result.stdout.strip()

        # Containers and other non-systemd environments have the systemctl
        # binary present but no systemd PID 1 to talk to. Detect that
        # explicitly instead of reporting a confusing "unexpected state".
        no_systemd = "not been booted with systemd" in result.stderr or "Host is down" in result.stderr
        if not state and no_systemd:
            return ServiceCheck(
                name=name,
                running=False,
                status=Status.UNKNOWN,
                detail="systemd is not running as PID 1 on this host (e.g. inside a container)",
                timestamp=utc_now(),
            )

        if state == "active":
            return ServiceCheck(
                name=name, running=True, status=Status.OK, detail="active", timestamp=utc_now()
            )
        if state in ("failed",):
            return ServiceCheck(
                name=name,
                running=False,
                status=Status.CRITICAL,
                detail="service is in a failed state",
                timestamp=utc_now(),
            )
        if state in ("inactive", "unknown"):
            return ServiceCheck(
                name=name,
                running=False,
                status=Status.WARNING,
                detail=f"service is {state}",
                timestamp=utc_now(),
            )
        return ServiceCheck(
            name=name,
            running=False,
            status=Status.WARNING,
            detail=f"unexpected systemctl state: {state!r}",
            timestamp=utc_now(),
        )

    def run_all(self) -> list[ServiceCheck]:
        return [self.check_service(name) for name in self.service_names]
