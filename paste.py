"""Insert text into the focused window — by paste (Ctrl+V) or by typing characters."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import time
import pyperclip
from pynput.keyboard import Controller, Key, KeyCode

_kbd = Controller()
_logger = logging.getLogger("whisper-dictate")
_user32 = ctypes.windll.user32


# --------------------------- Win32 SendInput structures (for type_text) ---------------------------

class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUT_UNION)]


_INPUT_KEYBOARD = 1
_KEYEVENTF_KEYUP = 0x0002
_KEYEVENTF_UNICODE = 0x0004
_VK_RETURN = 0x0D
_VK_TAB = 0x09


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


def _send_unicode_char(codepoint: int) -> None:
    """Inject a single Unicode code point as a synthesized keypress."""
    inputs = (_INPUT * 2)()
    inputs[0].type = _INPUT_KEYBOARD
    inputs[0].u.ki = _KEYBDINPUT(0, codepoint, _KEYEVENTF_UNICODE, 0, None)
    inputs[1].type = _INPUT_KEYBOARD
    inputs[1].u.ki = _KEYBDINPUT(0, codepoint, _KEYEVENTF_UNICODE | _KEYEVENTF_KEYUP, 0, None)
    _user32.SendInput(2, ctypes.byref(inputs), ctypes.sizeof(_INPUT))


def _send_vk(vk: int) -> None:
    """Inject a press+release for a virtual-key code (used for Enter and Tab)."""
    inputs = (_INPUT * 2)()
    inputs[0].type = _INPUT_KEYBOARD
    inputs[0].u.ki = _KEYBDINPUT(vk, 0, 0, 0, None)
    inputs[1].type = _INPUT_KEYBOARD
    inputs[1].u.ki = _KEYBDINPUT(vk, 0, _KEYEVENTF_KEYUP, 0, None)
    _user32.SendInput(2, ctypes.byref(inputs), ctypes.sizeof(_INPUT))


def type_text(text: str, char_delay: float = 0.003) -> None:
    """Type `text` character-by-character via Win32 SendInput with KEYEVENTF_UNICODE.

    Unicode-safe — handles Cyrillic and any BMP char regardless of the active
    keyboard layout (no VkKeyScan translation, the OS injects the code point directly).
    Surrogate pairs are sent for chars outside the BMP.
    """
    if not text:
        return
    win_title = _foreground_window_name()
    _logger.info("type: %d chars into window=%r", len(text), win_title[:80])
    for c in text:
        if c == "\n":
            _send_vk(_VK_RETURN)
        elif c == "\t":
            _send_vk(_VK_TAB)
        else:
            cp = ord(c)
            if cp > 0xFFFF:
                # Non-BMP — split into UTF-16 surrogate pair
                v = cp - 0x10000
                _send_unicode_char(0xD800 + (v >> 10))
                _send_unicode_char(0xDC00 + (v & 0x3FF))
            else:
                _send_unicode_char(cp)
        if char_delay > 0:
            time.sleep(char_delay)


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
