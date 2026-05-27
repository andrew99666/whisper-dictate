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

# Windows message constants for PostMessage-based typing
_WM_CHAR = 0x0102
_SMTO_NORMAL = 0x0000
_SMTO_ABORTIFHUNG = 0x0002
_kernel32 = ctypes.windll.kernel32

# Properly declare SendMessageTimeoutW so 64-bit pointer types are correct.
_user32.SendMessageTimeoutW.argtypes = [
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
    wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t),
]
_user32.SendMessageTimeoutW.restype = ctypes.c_size_t


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


_BATCH_MAX = 50         # max INPUT events per SendInput call (= 25 chars)
_BATCH_GAP = 0.005      # seconds between batches — gives the target app time to drain WM_CHAR


def _append_unicode(buf: list, codepoint: int) -> None:
    down = _INPUT()
    down.type = _INPUT_KEYBOARD
    down.u.ki = _KEYBDINPUT(0, codepoint, _KEYEVENTF_UNICODE, 0, None)
    up = _INPUT()
    up.type = _INPUT_KEYBOARD
    up.u.ki = _KEYBDINPUT(0, codepoint, _KEYEVENTF_UNICODE | _KEYEVENTF_KEYUP, 0, None)
    buf.append(down)
    buf.append(up)


def _append_vk(buf: list, vk: int) -> None:
    down = _INPUT()
    down.type = _INPUT_KEYBOARD
    down.u.ki = _KEYBDINPUT(vk, 0, 0, 0, None)
    up = _INPUT()
    up.type = _INPUT_KEYBOARD
    up.u.ki = _KEYBDINPUT(vk, 0, _KEYEVENTF_KEYUP, 0, None)
    buf.append(down)
    buf.append(up)


def _flush_batch(events: list) -> None:
    if not events:
        return
    n = len(events)
    arr = (_INPUT * n)(*events)
    sent = _user32.SendInput(n, ctypes.byref(arr), ctypes.sizeof(_INPUT))
    if sent != n:
        _logger.warning("SendInput accepted %d of %d events (Windows dropped some)", sent, n)
    events.clear()


def _find_focused_hwnd() -> int:
    """Return the HWND of the focused control of the foreground window.

    Walks AttachThreadInput so we can call GetFocus across threads. Falls back
    to the foreground window itself if no specific focus is reported.
    """
    fg = _user32.GetForegroundWindow()
    if not fg:
        return 0
    other_tid = _user32.GetWindowThreadProcessId(fg, None)
    our_tid = _kernel32.GetCurrentThreadId()
    focus = 0
    attached = False
    try:
        if other_tid and other_tid != our_tid:
            attached = bool(_user32.AttachThreadInput(our_tid, other_tid, True))
        focus = _user32.GetFocus()
    finally:
        if attached:
            _user32.AttachThreadInput(our_tid, other_tid, False)
    return focus or fg


def _send_char(target: int, codepoint: int) -> None:
    """SendMessageTimeoutW for one WM_CHAR. Blocks until target processes it."""
    result = ctypes.c_size_t(0)
    _user32.SendMessageTimeoutW(
        target, _WM_CHAR, codepoint, 0,
        _SMTO_NORMAL | _SMTO_ABORTIFHUNG, 100, ctypes.byref(result),
    )


def _type_chars(text: str, char_delay: float = 0.0) -> None:
    """Type chars via SendMessageTimeout(WM_CHAR) directly to the focused window.

    Synchronous send: each char is delivered and processed before we send the
    next. Eliminates any possibility of cross-thread message interleaving or
    OS-level rate limiting. Slower than PostMessage but guaranteed in-order.

    Works for standard Windows apps (Notepad, Office, IDEs, win32 dialogs).
    Doesn't work for games or apps that read raw input — paste mode is the
    right choice for those.

    `char_delay` is kept for API compatibility; not used.
    """
    if not text:
        return
    target = _find_focused_hwnd()
    if not target:
        _logger.warning("type: no focused window found")
        return
    for c in text:
        if c == "\n":
            # WM_CHAR for newline uses \r (0x0D); edit control turns it into a line break.
            _send_char(target, 0x0D)
        elif c == "\t":
            _send_char(target, 0x09)
        else:
            cp = ord(c)
            if cp > 0xFFFF:
                # Non-BMP — split into UTF-16 surrogate pair.
                v = cp - 0x10000
                _send_char(target, 0xD800 + (v >> 10))
                _send_char(target, 0xDC00 + (v & 0x3FF))
            else:
                _send_char(target, cp)


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
    _type_chars(text, char_delay)


def type_stream(chunks, char_delay: float = 0.003) -> str:
    """Type chunks from an iterator as they arrive (e.g. an LLM stream).

    Returns the concatenated text that was typed. Single log line for the whole
    stream rather than per-chunk noise. Any chunk-yielding exception propagates
    to the caller AFTER the partial text has been typed.
    """
    win_title = _foreground_window_name()
    _logger.info("type-stream: into window=%r", win_title[:80])
    parts: list[str] = []
    try:
        for chunk in chunks:
            if not chunk:
                continue
            _type_chars(chunk, char_delay)
            parts.append(chunk)
    finally:
        full = "".join(parts)
        _logger.info("type-stream done: %d chars", len(full))
    return full


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
