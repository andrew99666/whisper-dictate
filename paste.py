"""Clipboard + auto-paste into the focused window, with clipboard restore."""
from __future__ import annotations

import ctypes
import logging
import time
import pyperclip
from pynput.keyboard import Controller, Key, KeyCode

_kbd = Controller()
_logger = logging.getLogger("whisper-dictate")


def _foreground_window_name() -> str:
    """Return the title of the currently-focused window (Win32). Empty on failure."""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ""
        length = user32.GetWindowTextLengthW(hwnd) + 1
        buf = ctypes.create_unicode_buffer(length)
        user32.GetWindowTextW(hwnd, buf, length)
        return buf.value
    except Exception:
        return ""


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


def paste_text(text: str, restore_delay: float = 0.2, send_keys: bool = True) -> None:
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
        # Re-verify clipboard contents in case something mutated them between write and paste.
        pre_paste = _safe_get_clipboard()
        if pre_paste != text:
            _logger.warning("paste: clipboard changed before paste — expected %d chars, found %d",
                            len(text), len(pre_paste))
        win_title = _foreground_window_name()
        _logger.info("paste: sending Ctrl+V into window=%r", win_title[:80])
        _send_paste_chord()
        _logger.debug("paste: Ctrl+V sent")
    time.sleep(restore_delay)
    _safe_set_clipboard(prev)
