"""
Logging configuration for shogun-web.

Provides structured logging via StreamHandler (stdout).
Log output is captured by gunicorn via --access-logfile/--error-logfile.
RotatingFileHandler is intentionally omitted: gunicorn multi-worker processes
sharing a single RotatingFileHandler would corrupt log files on rotation.
"""

import logging
from datetime import datetime
from pathlib import Path


class DailyJsonlHandler(logging.Handler):
    """Daily JSONL file handler for audit logs. Multi-worker safe (no rotation)."""

    def __init__(self, log_dir: str | Path):
        super().__init__()
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            path = self.log_dir / f"{datetime.now().strftime('%Y-%m-%d')}.jsonl"
            with path.open("a") as f:
                f.write(self.format(record) + "\n")
        except Exception:
            self.handleError(record)


def setup_logging(
    level: int = logging.INFO,
    log_dir: str | Path | None = None,
) -> None:
    """Configure root logger with StreamHandler only.

    Also configures bakuhu.audit logger with DailyJsonlHandler for structured
    audit log files separated from gunicorn stdout.

    Args:
        level: Logging level for the root logger.
        log_dir: Directory for audit JSONL files. Defaults to
            <project_root>/logs/inter-bakuhu.
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

    if log_dir is None:
        # logging_config.py は app/ 配下なので、その親がproject root
        log_dir = Path(__file__).parent.parent / "logs" / "inter-bakuhu"

    audit = logging.getLogger("bakuhu.audit")
    audit.setLevel(logging.INFO)
    if not any(isinstance(h, DailyJsonlHandler) for h in audit.handlers):
        audit.addHandler(DailyJsonlHandler(log_dir))
    audit.propagate = False  # stdoutへの混在を防ぐ
