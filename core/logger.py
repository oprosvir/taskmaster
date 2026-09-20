# import copy
import logging
from pathlib import Path

from config import ConfigError

LOG_FORMAT = "[%(asctime)s] %(levelname)-8s %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


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

    return logger
