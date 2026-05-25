"""Clipboard + auto-paste into the focused window, with clipboard restore."""
from __future__ import annotations

import logging
import time
import pyperclip
from pynput.keyboard import Controller, Key, KeyCode

_kbd = Controller()
_logger = logging.getLogger("whisper-dictate")


def _safe_get_clipboard() -> str:
    try:
        v = pyperclip.paste()
        return v if v is not None else ""
    except Exception:
        return ""


def _safe_set_clipboard(text: str) -> None:
    try:
        pyperclip.copy(text)
    except Exception:
        pass


def _send_paste_chord() -> None:
    """Send Ctrl+V with small delays so the receiving app doesn't see a bare V keystroke.

    Some apps process V before Ctrl-down registers when keys fire back-to-back; the
    inter-key sleeps fix that, at the cost of a few milliseconds.
    """
    v_key = KeyCode.from_char("v")
    _kbd.press(Key.ctrl)
    time.sleep(0.03)
    _kbd.press(v_key)
    time.sleep(0.03)
    _kbd.release(v_key)
    time.sleep(0.03)
    _kbd.release(Key.ctrl)


def paste_text(text: str, restore_delay: float = 0.5, send_keys: bool = True) -> None:
    """Copy `text` to clipboard, send Ctrl+V, then restore the previous clipboard."""
    if not text:
        _logger.debug("paste: empty text, skipping")
        return
    prev = _safe_get_clipboard()
    _safe_set_clipboard(text)
    # Verify clipboard write actually took (Windows can reject very rapid writes)
    written = _safe_get_clipboard()
    if written != text:
        _logger.warning("paste: clipboard write mismatch — wrote %d chars, read back %d",
                        len(text), len(written))
    if send_keys:
        time.sleep(0.08)  # let OS register the new clipboard before the paste chord
        _logger.debug("paste: sending Ctrl+V")
        _send_paste_chord()
        _logger.debug("paste: Ctrl+V sent")
    time.sleep(restore_delay)
    _safe_set_clipboard(prev)
