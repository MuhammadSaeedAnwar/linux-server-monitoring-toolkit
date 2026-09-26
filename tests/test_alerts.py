from datetime import datetime, timezone

from monitoring import alerts
from monitoring.models import NetworkCheckResult, ServiceCheck, Status, SystemHealth


def _now():
    return datetime.now(timezone.utc)


def test_no_alerts_when_system_ok():
    health = SystemHealth(
        timestamp=_now(), cpu_percent=10, memory_percent=10, disk_percent=10,
        uptime_seconds=100, load_average_1m=0.1, load_average_5m=0.1, load_average_15m=0.1,
        status=Status.OK, warnings=[],
    )
    assert alerts.alerts_from_system_health(health) == []


def test_alert_per_warning_when_system_warning():
    health = SystemHealth(
        timestamp=_now(), cpu_percent=95, memory_percent=10, disk_percent=10,
        uptime_seconds=100, load_average_1m=0.1, load_average_5m=0.1, load_average_15m=0.1,
        status=Status.WARNING, warnings=["CPU usage 95.0% >= threshold 80%"],
    )
    result = alerts.alerts_from_system_health(health)
    assert len(result) == 1
    assert result[0].source == "system"
    assert result[0].severity == Status.WARNING


def test_service_alerts_only_for_unhealthy_services():
    checks = [
        ServiceCheck(name="nginx", running=True, status=Status.OK, detail="active", timestamp=_now()),
        ServiceCheck(name="postgresql", running=False, status=Status.CRITICAL, detail="failed", timestamp=_now()),
    ]
    result = alerts.alerts_from_service_checks(checks)
    assert len(result) == 1
    assert "postgresql" in result[0].message


def test_network_alerts_only_for_unhealthy_checks():
    checks = [
        NetworkCheckResult(check_type="dns", target="google.com", success=True, status=Status.OK, detail="ok", latency_ms=5.0, timestamp=_now()),
        NetworkCheckResult(check_type="tcp_port", target="db:5432", success=False, status=Status.CRITICAL, detail="refused", latency_ms=None, timestamp=_now()),
    ]
    result = alerts.alerts_from_network_checks(checks)
    assert len(result) == 1
    assert result[0].source == "network"
