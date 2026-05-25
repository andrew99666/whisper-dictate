"""User-facing feedback: beeps, toasts, logger setup."""
from __future__ import annotations

import logging
import threading
from logging.handlers import RotatingFileHandler

try:
    import winsound  # Windows-only stdlib module
    _HAVE_WINSOUND = True
except ImportError:
    _HAVE_WINSOUND = False

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


def beep(freq: int, dur_ms: int) -> None:
    """Non-blocking beep. Silent if not on Windows."""
    if not _HAVE_WINSOUND:
        return
    threading.Thread(target=winsound.Beep, args=(freq, dur_ms), daemon=True).start()


def beep_start() -> None:
    beep(880, 60)


def beep_stop() -> None:
    beep(660, 60)


def toast(title: str, body: str) -> None:
    try:
        Notification(app_id="Whisper Dictate", title=title, msg=body).show()
    except Exception:
        # Toast failure shouldn't crash the app
        _logger.exception("toast failed")
