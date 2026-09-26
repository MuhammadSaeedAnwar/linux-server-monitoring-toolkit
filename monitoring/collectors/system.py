"""System resource collection: CPU, RAM, disk, uptime, load average.

Uses psutil, which works cross-platform, but load average via
os.getloadavg() is POSIX-only (Linux/macOS) and is the primary target
here since Ubuntu is the deployment platform this project targets.
"""

from __future__ import annotations

import os
import time

import psutil

from monitoring.models import Status, SystemHealth, utc_now


class SystemCollector:
    def __init__(self, thresholds: dict[str, float]) -> None:
        self.cpu_warning = thresholds.get("cpu_percent_warning", 80)
        self.memory_warning = thresholds.get("memory_percent_warning", 85)
        self.disk_warning = thresholds.get("disk_percent_warning", 90)
        self.load_warning = thresholds.get("load_average_warning", 4.0)

    def collect(self, disk_path: str = "/") -> SystemHealth:
        cpu_percent = psutil.cpu_percent(interval=0.5)
        memory_percent = psutil.virtual_memory().percent
        disk_percent = psutil.disk_usage(disk_path).percent
        uptime_seconds = time.time() - psutil.boot_time()

        try:
            load1, load5, load15 = os.getloadavg()
        except (OSError, AttributeError):
            # Not available (e.g. Windows). Report as zero rather than crash.
            load1, load5, load15 = 0.0, 0.0, 0.0

        warnings: list[str] = []
        if cpu_percent >= self.cpu_warning:
            warnings.append(f"CPU usage {cpu_percent:.1f}% >= threshold {self.cpu_warning}%")
        if memory_percent >= self.memory_warning:
            warnings.append(f"Memory usage {memory_percent:.1f}% >= threshold {self.memory_warning}%")
        if disk_percent >= self.disk_warning:
            warnings.append(f"Disk usage {disk_percent:.1f}% >= threshold {self.disk_warning}%")
        if load1 >= self.load_warning:
            warnings.append(f"1m load average {load1:.2f} >= threshold {self.load_warning}")

        status = Status.WARNING if warnings else Status.OK

        return SystemHealth(
            timestamp=utc_now(),
            cpu_percent=cpu_percent,
            memory_percent=memory_percent,
            disk_percent=disk_percent,
            uptime_seconds=uptime_seconds,
            load_average_1m=load1,
            load_average_5m=load5,
            load_average_15m=load15,
            status=status,
            warnings=warnings,
        )
