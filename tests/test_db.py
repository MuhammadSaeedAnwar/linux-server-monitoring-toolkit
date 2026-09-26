from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from monitoring.config import DatabaseConfig
from monitoring.db import Database
from monitoring.models import AlertEvent, ServiceCheck, Status, SystemHealth


@pytest.fixture
def db_config():
    return DatabaseConfig(host="localhost", port=5432, name="toolkit", user="u", password="p")


@patch("monitoring.db.psycopg2.connect")
def test_connect_sets_autocommit(mock_connect, db_config):
    mock_conn = MagicMock()
    mock_connect.return_value = mock_conn

    db = Database(db_config)
    db.connect()

    mock_connect.assert_called_once_with(
        host="localhost", port=5432, dbname="toolkit", user="u", password="p", connect_timeout=5
    )
    assert mock_conn.autocommit is True


def test_conn_property_raises_before_connect(db_config):
    db = Database(db_config)
    with pytest.raises(RuntimeError):
        _ = db.conn


@patch("monitoring.db.psycopg2.connect")
def test_insert_system_health_executes_query(mock_connect, db_config):
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_connect.return_value = mock_conn

    db = Database(db_config)
    db.connect()

    health = SystemHealth(
        timestamp=datetime.now(timezone.utc), cpu_percent=1, memory_percent=2, disk_percent=3,
        uptime_seconds=4, load_average_1m=0.1, load_average_5m=0.1, load_average_15m=0.1,
        status=Status.OK, warnings=[],
    )
    db.insert_system_health(health)

    assert mock_cursor.execute.called
    query = mock_cursor.execute.call_args[0][0]
    assert "INSERT INTO system_health_checks" in query


@patch("monitoring.db.psycopg2.connect")
def test_insert_alert_executes_query(mock_connect, db_config):
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_connect.return_value = mock_conn

    db = Database(db_config)
    db.connect()

    alert = AlertEvent(source="system", message="test", severity=Status.WARNING, timestamp=datetime.now(timezone.utc))
    db.insert_alert(alert)

    query = mock_cursor.execute.call_args[0][0]
    assert "INSERT INTO alerts" in query


@patch("monitoring.db.psycopg2.connect")
def test_context_manager_closes_connection(mock_connect, db_config):
    mock_conn = MagicMock()
    mock_connect.return_value = mock_conn

    with Database(db_config) as db:
        assert db.conn is mock_conn

    mock_conn.close.assert_called_once()
