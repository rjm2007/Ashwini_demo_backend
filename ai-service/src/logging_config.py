import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging() -> None:
    """Configure root logging: always stdout; optional rotating file under LOG_DIR."""
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_format = "%(asctime)s %(levelname)s %(name)s :: %(message)s"

    root = logging.getLogger()
    root.setLevel(log_level)

    # Avoid duplicate handlers if setup_logging is called twice (e.g. hot reload).
    if root.handlers:
        return

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(log_format))
    root.addHandler(console)

    log_dir = os.getenv("LOG_DIR", "").strip()
    if log_dir:
        path = Path(log_dir)
        path.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            path / "app.log",
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(logging.Formatter(log_format))
        root.addHandler(file_handler)
        logging.getLogger(__name__).info("File logging enabled dir=%s", path)
