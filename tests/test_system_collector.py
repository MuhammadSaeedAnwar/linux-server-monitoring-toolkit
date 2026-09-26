from unittest.mock import MagicMock, patch

from monitoring.collectors.system import SystemCollector
from monitoring.models import Status


def _mem_mock(percent: float) -> MagicMock:
    m = MagicMock()
    m.percent = percent
    return m


def _disk_mock(percent: float) -> MagicMock:
    m = MagicMock()
    m.percent = percent
    return m


@patch("monitoring.collectors.system.os.getloadavg", return_value=(0.5, 0.4, 0.3))
@patch("monitoring.collectors.system.psutil.boot_time", return_value=0.0)
@patch("monitoring.collectors.system.psutil.disk_usage")
@patch("monitoring.collectors.system.psutil.virtual_memory")
@patch("monitoring.collectors.system.psutil.cpu_percent", return_value=10.0)
def test_ok_status_when_under_thresholds(mock_cpu, mock_vmem, mock_disk, mock_boot, mock_load):
    mock_vmem.return_value = _mem_mock(20.0)
    mock_disk.return_value = _disk_mock(30.0)

    collector = SystemCollector({"cpu_percent_warning": 80, "memory_percent_warning": 85, "disk_percent_warning": 90, "load_average_warning": 4.0})
    result = collector.collect()

    assert result.status == Status.OK
    assert result.warnings == []
    assert result.cpu_percent == 10.0


@patch("monitoring.collectors.system.os.getloadavg", return_value=(0.5, 0.4, 0.3))
@patch("monitoring.collectors.system.psutil.boot_time", return_value=0.0)
@patch("monitoring.collectors.system.psutil.disk_usage")
@patch("monitoring.collectors.system.psutil.virtual_memory")
@patch("monitoring.collectors.system.psutil.cpu_percent", return_value=95.0)
def test_warning_status_when_cpu_over_threshold(mock_cpu, mock_vmem, mock_disk, mock_boot, mock_load):
    mock_vmem.return_value = _mem_mock(20.0)
    mock_disk.return_value = _disk_mock(30.0)

    collector = SystemCollector({"cpu_percent_warning": 80, "memory_percent_warning": 85, "disk_percent_warning": 90, "load_average_warning": 4.0})
    result = collector.collect()

    assert result.status == Status.WARNING
    assert any("CPU" in w for w in result.warnings)


@patch("monitoring.collectors.system.os.getloadavg", side_effect=AttributeError)
@patch("monitoring.collectors.system.psutil.boot_time", return_value=0.0)
@patch("monitoring.collectors.system.psutil.disk_usage")
@patch("monitoring.collectors.system.psutil.virtual_memory")
@patch("monitoring.collectors.system.psutil.cpu_percent", return_value=5.0)
def test_missing_loadavg_defaults_to_zero(mock_cpu, mock_vmem, mock_disk, mock_boot, mock_load):
    mock_vmem.return_value = _mem_mock(10.0)
    mock_disk.return_value = _disk_mock(10.0)

    collector = SystemCollector({})
    result = collector.collect()

    assert result.load_average_1m == 0.0
    assert result.load_average_5m == 0.0
