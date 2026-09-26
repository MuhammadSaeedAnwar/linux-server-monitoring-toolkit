import socket
import subprocess
from unittest.mock import MagicMock, patch

from monitoring.collectors.network import NetworkCollector
from monitoring.models import Status


def make_collector() -> NetworkCollector:
    return NetworkCollector({})


@patch("monitoring.collectors.network.socket.gethostbyname", return_value="93.184.216.34")
def test_dns_success(mock_resolve):
    result = make_collector().check_dns("example.com")
    assert result.success is True
    assert result.status == Status.OK
    assert result.check_type == "dns"


@patch("monitoring.collectors.network.socket.gethostbyname", side_effect=socket.gaierror("nope"))
def test_dns_failure(mock_resolve):
    result = make_collector().check_dns("nonexistent.invalid")
    assert result.success is False
    assert result.status == Status.CRITICAL


@patch("monitoring.collectors.network.socket.create_connection")
def test_tcp_port_success(mock_conn):
    mock_conn.return_value.__enter__.return_value = MagicMock()
    result = make_collector().check_tcp_port("localhost", 5432, label="postgres")
    assert result.success is True
    assert result.target == "postgres"


@patch("monitoring.collectors.network.socket.create_connection", side_effect=ConnectionRefusedError)
def test_tcp_port_refused(mock_conn):
    result = make_collector().check_tcp_port("localhost", 9999)
    assert result.success is False
    assert result.status == Status.CRITICAL


@patch("monitoring.collectors.network.shutil.which", return_value=None)
def test_ping_reports_unknown_when_binary_missing(mock_which):
    result = make_collector().check_ping("8.8.8.8")
    assert result.status == Status.UNKNOWN
    assert result.success is False


@patch("monitoring.collectors.network.shutil.which", return_value="/bin/ping")
@patch("monitoring.collectors.network.subprocess.run")
def test_ping_success_parses_return_code(mock_run, mock_which):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="rtt min/avg/max/mdev = 10.0/12.5/15.0/1.0 ms", stderr=""
    )
    result = make_collector().check_ping("8.8.8.8", count=3, timeout_seconds=2)
    assert result.success is True
    assert result.status == Status.OK
    assert result.latency_ms == 12.5


@patch("monitoring.collectors.network.shutil.which", return_value="/bin/ping")
@patch("monitoring.collectors.network.subprocess.run")
def test_ping_failure_on_nonzero_exit(mock_run, mock_which):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr="Destination Host Unreachable"
    )
    result = make_collector().check_ping("192.0.2.1")
    assert result.success is False
    assert result.status == Status.CRITICAL


@patch("monitoring.collectors.network.urllib.request.urlopen")
def test_http_check_success(mock_urlopen):
    mock_response = MagicMock()
    mock_response.getcode.return_value = 200
    mock_urlopen.return_value.__enter__.return_value = mock_response
    result = make_collector().check_http("https://example.com", expected_status=200)
    assert result.success is True
    assert result.status == Status.OK


@patch("monitoring.collectors.network.urllib.request.urlopen")
def test_http_check_unexpected_status(mock_urlopen):
    mock_response = MagicMock()
    mock_response.getcode.return_value = 500
    mock_urlopen.return_value.__enter__.return_value = mock_response
    result = make_collector().check_http("https://example.com", expected_status=200)
    assert result.success is False
    assert result.status == Status.WARNING
