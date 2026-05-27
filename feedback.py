"""Logger setup + Windows toast notifications."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from winotify import Notification

_logger = logging.getLogger("whisper-dictate")


def setup_logging(log_path: str) -> logging.Logger:
    _logger.setLevel(logging.DEBUG)
    # Avoid duplicate handlers if called twice (e.g. in tests)
    if not any(isinstance(h, RotatingFileHandler) for h in _logger.handlers):
        handler = RotatingFileHandler(log_path, maxBytes=200_000, backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        _logger.addHandler(handler)
    return _logger


def toast(title: str, body: str) -> None:
    try:
        Notification(app_id="Whisper Dictate", title=title, msg=body).show()
    except Exception:
        # Toast failure shouldn't crash the app
        _logger.exception("toast failed")
