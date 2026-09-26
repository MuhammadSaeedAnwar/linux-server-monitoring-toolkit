"""Typed data structures shared across collectors, alerts, and storage."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class Status(str, Enum):
    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"
    ERROR = "error"
    UNKNOWN = "unknown"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class SystemHealth:
    """Snapshot of host resource usage."""

    timestamp: datetime
    cpu_percent: float
    memory_percent: float
    disk_percent: float
    uptime_seconds: float
    load_average_1m: float
    load_average_5m: float
    load_average_15m: float
    status: Status
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        d["timestamp"] = self.timestamp.isoformat()
        d["status"] = self.status.value
        return d


@dataclass
class ServiceCheck:
    """Result of checking a single system service."""

    name: str
    running: bool
    status: Status
    detail: str
    timestamp: datetime

    def to_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        d["timestamp"] = self.timestamp.isoformat()
        d["status"] = self.status.value
        return d


@dataclass
class NetworkCheckResult:
    """Result of a single network diagnostic (dns/ping/tcp/http/traceroute)."""

    check_type: str
    target: str
    success: bool
    status: Status
    detail: str
    latency_ms: Optional[float]
    timestamp: datetime

    def to_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        d["timestamp"] = self.timestamp.isoformat()
        d["status"] = self.status.value
        return d


@dataclass
class AlertEvent:
    """A raised alert, generated from thresholds or failed checks."""

    source: str          # e.g. "system", "network", "service"
    message: str
    severity: Status
    timestamp: datetime

    def to_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        d["timestamp"] = self.timestamp.isoformat()
        d["severity"] = self.severity.value
        return d
