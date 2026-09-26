"""Turns raw check results into alert events worth storing/surfacing.

Kept deliberately simple: an alert is generated whenever a check comes
back as WARNING, CRITICAL, or ERROR. This is not a full alerting engine
(no dedupe window, no escalation policies) -- a realistic scope for a
solo/portfolio project, called out explicitly as a limitation in the
README.
"""

from __future__ import annotations

from monitoring.models import (
    AlertEvent,
    NetworkCheckResult,
    ServiceCheck,
    Status,
    SystemHealth,
    utc_now,
)

_ALERTABLE = {Status.WARNING, Status.CRITICAL, Status.ERROR}


def alerts_from_system_health(health: SystemHealth) -> list[AlertEvent]:
    if health.status not in _ALERTABLE:
        return []
    return [
        AlertEvent(source="system", message=warning, severity=health.status, timestamp=utc_now())
        for warning in health.warnings
    ] or [
        AlertEvent(
            source="system",
            message=f"System health status is {health.status.value}",
            severity=health.status,
            timestamp=utc_now(),
        )
    ]


def alerts_from_service_checks(checks: list[ServiceCheck]) -> list[AlertEvent]:
    return [
        AlertEvent(
            source="service",
            message=f"Service '{c.name}' is {c.status.value}: {c.detail}",
            severity=c.status,
            timestamp=utc_now(),
        )
        for c in checks
        if c.status in _ALERTABLE
    ]


def alerts_from_network_checks(checks: list[NetworkCheckResult]) -> list[AlertEvent]:
    return [
        AlertEvent(
            source="network",
            message=f"{c.check_type} check for '{c.target}' is {c.status.value}: {c.detail}",
            severity=c.status,
            timestamp=utc_now(),
        )
        for c in checks
        if c.status in _ALERTABLE
    ]
