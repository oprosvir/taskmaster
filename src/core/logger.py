import logging
import sys
from logging.handlers import SysLogHandler
from pathlib import Path

from src.config import ConfigError

LOG_FORMAT = "[%(asctime)s] %(levelname)-8s %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
SYSLOG_PATH = "/dev/log"

# ANSI color codes
COLORS = {
    logging.DEBUG: "\033[36m",      # cyan
    logging.INFO: "\033[32m",       # green
    logging.WARNING: "\033[33m",    # yellow
    logging.ERROR: "\033[31m",      # red
    logging.CRITICAL: "\033[35m",   # magenta
}
RESET = "\033[0m"


class ColoredFormatter(logging.Formatter):
    """Formatter that adds ANSI color codes based on log level."""

    def format(self, record: logging.LogRecord) -> str:
        color = COLORS.get(record.levelno, "")
        record.levelname = f"{color}{record.levelname:<8}{RESET}"
        return super().format(record)


def setup_logging(logfile: Path, loglevel: str):
    """Configure and return the application-wide logger."""
    logger = logging.getLogger("taskmasterd")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(getattr(logging, loglevel))

    try:
        logfile.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(logfile, encoding="utf-8")
    except OSError as e:
        raise ConfigError(f"Cannot create log directory for {logfile}: {e}")

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_formatter = ColoredFormatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    stream_handler.setFormatter(stream_formatter)
    logger.addHandler(stream_handler)

    # Check logs: journalctl -f
    syslog_handler = SysLogHandler(address=SYSLOG_PATH)
    syslog_handler.setLevel(logging.WARNING)
    syslog_formatter = logging.Formatter("%(name)s: %(levelname)s - %(message)s")
    syslog_handler.setFormatter(syslog_formatter)
    logger.addHandler(syslog_handler)

    return logger
