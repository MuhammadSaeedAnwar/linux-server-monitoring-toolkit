import io
import json
import logging

from monitoring.logger import setup_logging


def test_logs_go_to_stderr_not_stdout(capsys):
    logger = setup_logging(level="info")
    logger.error("db is down")
    captured = capsys.readouterr()
    assert "db is down" in captured.err
    assert captured.out == ""


def test_json_format_emits_one_json_object_per_line():
    stream = io.StringIO()
    logger = setup_logging(level="info", json_format=True, stream=stream)
    logger.warning("hello")
    record = json.loads(stream.getvalue().strip())
    assert record["level"] == "WARNING" and record["message"] == "hello"


def test_level_is_applied_and_unknown_falls_back_to_info():
    assert setup_logging(level="debug").level == logging.DEBUG
    assert setup_logging(level="ERROR").level == logging.ERROR
    assert setup_logging(level="nonsense").level == logging.INFO


def test_setup_is_idempotent():
    setup_logging()
    logger = setup_logging()
    assert len(logger.handlers) == 1
