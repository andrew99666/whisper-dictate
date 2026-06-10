"""Clipboard + auto-paste (Ctrl+V) into the focused window."""
from __future__ import annotations

import ctypes
import logging
import threading
import time
from ctypes import wintypes
import pyperclip
from pynput.keyboard import Controller, Key, KeyCode

_kbd = Controller()
_logger = logging.getLogger("whisper-dictate")
DEFAULT_RESTORE_DELAY = 1.0
CLIPBOARD_SETTLE_DELAY = 0.05

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
VK_LCONTROL = 0xA2
VK_V = 0x56

ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong
user32 = ctypes.WinDLL("user32", use_last_error=True)


class KEYBDINPUT(ctypes.Structure):
    _fields_ = (
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    )


class MOUSEINPUT(ctypes.Structure):
    _fields_ = (
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    )


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = (
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    )


class INPUT_UNION(ctypes.Union):
    _fields_ = (
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    )


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = (
        ("type", wintypes.DWORD),
        ("u", INPUT_UNION),
    )


user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT


def _foreground_window_name() -> str:
    """Return the title of the currently-focused window (Win32). Empty on failure."""
    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ""
        length = user32.GetWindowTextLengthW(hwnd) + 1
        buf = ctypes.create_unicode_buffer(length)
        user32.GetWindowTextW(hwnd, buf, length)
        return buf.value
    except Exception:
        return ""


def _window_class_name(hwnd: int) -> str:
    try:
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, len(buf))
        return buf.value
    except Exception:
        return ""


def _foreground_window_snapshot() -> str:
    """Small diagnostic string for the current foreground window."""
    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return "title='' class=''"
        title = _foreground_window_name()
        klass = _window_class_name(hwnd)
        return f"title={title!r} class={klass!r}"
    except Exception:
        return "title='' class=''"


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


def _send_key(vk: int, key_up: bool = False) -> bool:
    flags = KEYEVENTF_KEYUP if key_up else 0
    event = INPUT(
        type=INPUT_KEYBOARD,
        ki=KEYBDINPUT(
            wVk=vk,
            wScan=0,
            dwFlags=flags,
            time=0,
            dwExtraInfo=ULONG_PTR(0),
        ),
    )
    sent = user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT))
    if sent != 1:
        err = ctypes.get_last_error()
        _logger.warning("paste: SendInput vk=0x%02x up=%s failed sent=%s err=%s",
                        vk, key_up, sent, err)
        return False
    return True


def _send_paste_chord_sendinput() -> bool:
    ok = True
    ok = _send_key(VK_LCONTROL) and ok
    time.sleep(0.06)
    ok = _send_key(VK_V) and ok
    time.sleep(0.04)
    ok = _send_key(VK_V, key_up=True) and ok
    time.sleep(0.04)
    ok = _send_key(VK_LCONTROL, key_up=True) and ok
    if ok:
        _logger.debug("paste: Ctrl+V sent via SendInput")
    return ok


def _send_paste_chord_pynput() -> None:
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


def _send_paste_chord() -> str:
    if _send_paste_chord_sendinput():
        return "sendinput"
    _logger.warning("paste: falling back to pynput Ctrl+V")
    _send_paste_chord_pynput()
    return "pynput"


def paste_text(text: str, restore_clipboard: bool = False,
               restore_delay: float = DEFAULT_RESTORE_DELAY,
               send_keys: bool = True) -> None:
    """Copy `text` to clipboard, send Ctrl+V, optionally restore previous clipboard."""
    if not text:
        _logger.debug("paste: empty text, skipping")
        return
    prev = _safe_get_clipboard() if restore_clipboard else ""
    _safe_set_clipboard(text)
    time.sleep(CLIPBOARD_SETTLE_DELAY)
    # Verify clipboard write actually took (Windows can reject very rapid writes)
    written = _safe_get_clipboard()
    if written != text:
        _logger.warning("paste: clipboard write mismatch — wrote %d chars, read back %d",
                        len(text), len(written))
    if send_keys:
        win = _foreground_window_snapshot()
        _logger.info("paste: sending Ctrl+V into window=%s", win[:160])
        method = _send_paste_chord()
        _logger.debug("paste: Ctrl+V sent (method=%s)", method)
    if not restore_clipboard:
        _logger.debug("paste: leaving dictated text on clipboard")
        return
    if restore_delay <= 0:
        _safe_set_clipboard(prev)
        return
    restore = threading.Timer(restore_delay, _safe_set_clipboard, args=(prev,))
    restore.daemon = True
    restore.start()
    _logger.debug("paste: clipboard restore scheduled in %.1fs", restore_delay)
