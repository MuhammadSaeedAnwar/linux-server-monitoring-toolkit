"""Structured logging setup.

Supports plain text (for a terminal) or single-line JSON (for log
aggregation / piping into other tools) depending on config.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def setup_logging(level: str = "info", json_format: bool = False) -> logging.Logger:
    """Configure and return the toolkit's root logger.

    Idempotent: safe to call multiple times (e.g. once per CLI invocation)
    without stacking duplicate handlers.
    """
    logger = logging.getLogger("toolkit")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    if json_format:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def get_logger(name: str = "toolkit") -> logging.Logger:
    return logging.getLogger(name)
