"""Network diagnostics: DNS, ping, TCP port checks, HTTP health checks,
and traceroute.

External commands (ping, traceroute) are invoked via subprocess with a
fixed argument list (never shell=True, never string-built commands) to
avoid shell injection, and with explicit timeouts so a hung network
target can never hang the whole monitoring loop.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any

from monitoring.models import NetworkCheckResult, Status, utc_now


class NetworkCollector:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config or {}

    # -- DNS -----------------------------------------------------------
    def check_dns(self, hostname: str) -> NetworkCheckResult:
        start = time.monotonic()
        try:
            socket.gethostbyname(hostname)
            elapsed_ms = (time.monotonic() - start) * 1000
            return NetworkCheckResult(
                check_type="dns",
                target=hostname,
                success=True,
                status=Status.OK,
                detail=f"Resolved {hostname} in {elapsed_ms:.1f} ms",
                latency_ms=elapsed_ms,
                timestamp=utc_now(),
            )
        except socket.gaierror as exc:
            return NetworkCheckResult(
                check_type="dns",
                target=hostname,
                success=False,
                status=Status.CRITICAL,
                detail=f"DNS resolution failed: {exc}",
                latency_ms=None,
                timestamp=utc_now(),
            )

    # -- Ping ------------------------------------------------------------
    def check_ping(self, host: str, count: int = 3, timeout_seconds: int = 2) -> NetworkCheckResult:
        if shutil.which("ping") is None:
            return NetworkCheckResult(
                check_type="ping",
                target=host,
                success=False,
                status=Status.UNKNOWN,
                detail="'ping' binary not available on this system",
                latency_ms=None,
                timestamp=utc_now(),
            )
        cmd = ["ping", "-c", str(count), "-W", str(timeout_seconds), host]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout_seconds * count + 5
            )
        except subprocess.TimeoutExpired:
            return NetworkCheckResult(
                check_type="ping",
                target=host,
                success=False,
                status=Status.CRITICAL,
                detail=f"ping to {host} timed out",
                latency_ms=None,
                timestamp=utc_now(),
            )

        latency_ms = self._parse_avg_latency(result.stdout)
        if result.returncode == 0:
            return NetworkCheckResult(
                check_type="ping",
                target=host,
                success=True,
                status=Status.OK,
                detail=f"{count} packets sent, host reachable",
                latency_ms=latency_ms,
                timestamp=utc_now(),
            )
        return NetworkCheckResult(
            check_type="ping",
            target=host,
            success=False,
            status=Status.CRITICAL,
            detail=f"Host unreachable (exit code {result.returncode}): {result.stderr.strip() or result.stdout.strip()}",
            latency_ms=None,
            timestamp=utc_now(),
        )

    @staticmethod
    def _parse_avg_latency(ping_output: str) -> float | None:
        # Linux iputils-ping prints a line like:
        # rtt min/avg/max/mdev = 12.1/13.4/15.0/1.0 ms
        for line in ping_output.splitlines():
            if "min/avg/max" in line or "= " in line and "/" in line:
                try:
                    stats = line.split("=")[1].strip().split()[0]
                    avg = float(stats.split("/")[1])
                    return avg
                except (IndexError, ValueError):
                    continue
        return None

    # -- TCP port --------------------------------------------------------
    def check_tcp_port(self, host: str, port: int, timeout_seconds: float = 3.0, label: str | None = None) -> NetworkCheckResult:
        target_label = label or f"{host}:{port}"
        start = time.monotonic()
        try:
            with socket.create_connection((host, port), timeout=timeout_seconds):
                elapsed_ms = (time.monotonic() - start) * 1000
                return NetworkCheckResult(
                    check_type="tcp_port",
                    target=target_label,
                    success=True,
                    status=Status.OK,
                    detail=f"Connected to {host}:{port} in {elapsed_ms:.1f} ms",
                    latency_ms=elapsed_ms,
                    timestamp=utc_now(),
                )
        except (socket.timeout, ConnectionRefusedError, OSError) as exc:
            return NetworkCheckResult(
                check_type="tcp_port",
                target=target_label,
                success=False,
                status=Status.CRITICAL,
                detail=f"Could not connect to {host}:{port}: {exc}",
                latency_ms=None,
                timestamp=utc_now(),
            )

    # -- HTTP/HTTPS --------------------------------------------------------
    def check_http(self, url: str, expected_status: int = 200, timeout_seconds: float = 5.0) -> NetworkCheckResult:
        start = time.monotonic()
        try:
            req = urllib.request.Request(url, method="GET", headers={"User-Agent": "linux-toolkit-healthcheck/1.0"})
            with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                elapsed_ms = (time.monotonic() - start) * 1000
                status_code = resp.getcode()
                if status_code == expected_status:
                    return NetworkCheckResult(
                        check_type="http",
                        target=url,
                        success=True,
                        status=Status.OK,
                        detail=f"HTTP {status_code} in {elapsed_ms:.1f} ms",
                        latency_ms=elapsed_ms,
                        timestamp=utc_now(),
                    )
                return NetworkCheckResult(
                    check_type="http",
                    target=url,
                    success=False,
                    status=Status.WARNING,
                    detail=f"Unexpected status {status_code}, expected {expected_status}",
                    latency_ms=elapsed_ms,
                    timestamp=utc_now(),
                )
        except urllib.error.HTTPError as exc:
            return NetworkCheckResult(
                check_type="http",
                target=url,
                success=False,
                status=Status.WARNING,
                detail=f"HTTP error {exc.code}: {exc.reason}",
                latency_ms=None,
                timestamp=utc_now(),
            )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return NetworkCheckResult(
                check_type="http",
                target=url,
                success=False,
                status=Status.CRITICAL,
                detail=f"Request failed: {exc}",
                latency_ms=None,
                timestamp=utc_now(),
            )

    # -- Traceroute ---------------------------------------------------------
    def check_traceroute(self, host: str, timeout_seconds: int = 10) -> NetworkCheckResult:
        binary = shutil.which("traceroute") or shutil.which("tracepath")
        if binary is None:
            return NetworkCheckResult(
                check_type="traceroute",
                target=host,
                success=False,
                status=Status.UNKNOWN,
                detail="Neither 'traceroute' nor 'tracepath' is installed on this system",
                latency_ms=None,
                timestamp=utc_now(),
            )
        cmd = [binary, host]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_seconds)
            hop_count = max(0, len(result.stdout.strip().splitlines()) - 1)
            return NetworkCheckResult(
                check_type="traceroute",
                target=host,
                success=result.returncode == 0,
                status=Status.OK if result.returncode == 0 else Status.WARNING,
                detail=f"{hop_count} hops recorded" if result.returncode == 0 else result.stderr.strip(),
                latency_ms=None,
                timestamp=utc_now(),
            )
        except subprocess.TimeoutExpired:
            return NetworkCheckResult(
                check_type="traceroute",
                target=host,
                success=False,
                status=Status.WARNING,
                detail=f"traceroute to {host} timed out after {timeout_seconds}s",
                latency_ms=None,
                timestamp=utc_now(),
            )

    # -- Run everything from config --------------------------------------
    def run_all(self) -> list[NetworkCheckResult]:
        results: list[NetworkCheckResult] = []

        for hostname in self.config.get("dns", {}).get("hostnames", []):
            results.append(self.check_dns(hostname))

        ping_cfg = self.config.get("ping", {})
        for target in ping_cfg.get("targets", []):
            results.append(
                self.check_ping(
                    target,
                    count=ping_cfg.get("count", 3),
                    timeout_seconds=ping_cfg.get("timeout_seconds", 2),
                )
            )

        for entry in self.config.get("tcp_ports", []):
            results.append(
                self.check_tcp_port(entry["host"], entry["port"], label=entry.get("label"))
            )

        for entry in self.config.get("http_checks", []):
            results.append(
                self.check_http(
                    entry["url"],
                    expected_status=entry.get("expected_status", 200),
                    timeout_seconds=entry.get("timeout_seconds", 5),
                )
            )

        for target in self.config.get("traceroute", {}).get("targets", []):
            results.append(self.check_traceroute(target))

        return results
