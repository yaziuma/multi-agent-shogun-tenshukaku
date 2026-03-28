"""
Logging configuration for shogun-web.

Provides structured logging via StreamHandler (stdout).
Log output is captured by gunicorn via --access-logfile/--error-logfile.
RotatingFileHandler is intentionally omitted: gunicorn multi-worker processes
sharing a single RotatingFileHandler would corrupt log files on rotation.
"""

import logging
from pathlib import Path  # noqa: F401 — kept for potential future use


def setup_logging(
    level: int = logging.INFO,
) -> None:
    """Configure root logger with StreamHandler only.

    Args:
        level: Logging level for the root logger.
    """
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    if not root_logger.handlers:
        root_logger.addHandler(stream_handler)
    else:
        root_logger.handlers.clear()
        root_logger.addHandler(stream_handler)

    root_logger.setLevel(level)
