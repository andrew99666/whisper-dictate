"""Whisper Dictate — push-to-talk voice dictation for Windows.

Hold the configured hotkey (default: Right Ctrl) to record. Release to transcribe
(Groq Whisper), polish (Gemini), and paste into the focused window.
"""
from __future__ import annotations

import faulthandler
import os
import re
import sys
import threading
import time
import traceback

from dotenv import load_dotenv
load_dotenv()

from pynput import keyboard
from PySide6.QtCore import QMetaObject, Qt
from PySide6.QtWidgets import QApplication

import config as cfg_mod
from audio import Recorder, SAMPLE_RATE, pad_to_min_duration
from stt import transcribe
from llm import polish
from paste import paste_text
from tray import Tray
from feedback import setup_logging, toast
from mic_control import get_mic_control
from overlay import Overlay

CFG = cfg_mod.load()

# Resolve relative log paths against the script directory so the log lands
# in a predictable place regardless of the caller's CWD.
_log_path = CFG.log_path
if not os.path.isabs(_log_path):
    _log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), _log_path)
logger = setup_logging(_log_path)


# ---- crash diagnostics ----------------------------------------------------
# pythonw.exe silently discards stderr. Without these hooks an unhandled
# exception in any worker thread, or a segfault in PortAudio / Qt / ctypes,
# just kills the process with no trace anywhere.

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_stderr_log_path = os.path.join(_SCRIPT_DIR, "stderr.log")
_fault_log_path = os.path.join(_SCRIPT_DIR, "fault.log")

# Redirect Python's sys.stderr to a file so tracebacks that bypass our logger
# still land somewhere readable.
try:
    sys.stderr = open(_stderr_log_path, "a", buffering=1, encoding="utf-8")
except Exception:
    pass

# faulthandler dumps native C-level stack traces on SIGSEGV, abort, etc.
# Held open for the process lifetime.
try:
    _fault_file = open(_fault_log_path, "a", buffering=1, encoding="utf-8")
    faulthandler.enable(file=_fault_file, all_threads=True)
except Exception:
    pass


def _log_main_excepthook(exc_type, exc_value, exc_tb):
    logger.error("unhandled exception (main thread):",
                 exc_info=(exc_type, exc_value, exc_tb))


def _log_thread_excepthook(args):
    # args is a threading.ExceptHookArgs namedtuple
    logger.error("unhandled exception (thread=%s):",
                 getattr(args.thread, "name", "?"),
                 exc_info=(args.exc_type, args.exc_value, args.exc_traceback))


sys.excepthook = _log_main_excepthook
threading.excepthook = _log_thread_excepthook


def _parse_hotkey(name: str):
    """Map a config string like 'ctrl_r' to a pynput Key."""
    if hasattr(keyboard.Key, name):
        return getattr(keyboard.Key, name)
    if len(name) == 1:
        return keyboard.KeyCode.from_char(name)
    raise ValueError(f"unknown hotkey {name!r}; use a pynput Key name (e.g. ctrl_r, f9)")


PTT_KEY = _parse_hotkey(CFG.hotkey)

_recorder = Recorder(device=CFG.mic_device)
_recording = False
_recording_lock = threading.Lock()  # protects _recording transitions
_processing_lock = threading.Lock()
_tray: Tray | None = None
_overlay: Overlay | None = None
_listener: keyboard.Listener | None = None
_qt_app: QApplication | None = None


def _set_state(state: str) -> None:
    if _tray is not None:
        _tray.set_state(state)
    if _overlay is not None:
        _overlay.set_state(state)


def _timing_summary(timings: dict[str, float]) -> str:
    return " ".join(f"{name}={value:.0f}ms" for name, value in timings.items())


def _process(audio, rate: int, stop_ms: float = 0.0) -> None:
    """STT -> polish -> paste. Runs in a worker thread."""
    if not _processing_lock.acquire(blocking=False):
        logger.info("dropped utterance: previous pipeline still running")
        # The previous pipeline is still going — reflect that in the overlay
        # so it doesn't stay stuck on "recording" (set by on_press).
        _set_state("processing")
        return
    timings: dict[str, float] = {}
    if stop_ms:
        timings["stop"] = stop_ms
    pipeline_t0 = time.perf_counter()
    try:
        _set_state("processing")
        # Silent-audio guard: if the recorded buffer is essentially silent, skip
        # the API call. Otherwise Whisper hallucinates "Thank you" / "Bye" and we
        # paste that gibberish into the user's window. Cause is usually a muted
        # mic, a stale Bluetooth profile, or the callback API failing for the device.
        if audio.size > 0:
            import numpy as _np
            t0 = time.perf_counter()
            peak = float(_np.max(_np.abs(audio)))
            timings["silence_check"] = (time.perf_counter() - t0) * 1000.0
            if peak < 0.005:
                logger.warning("silent audio (peak=%.5f, dur=%.2fs) — skipping pipeline",
                               peak, audio.size / rate)
                if CFG.enable_toasts:
                    toast("Whisper Dictate",
                          "Mic captured silence — check that it's unmuted and selected")
                return
        t0 = time.perf_counter()
        padded = pad_to_min_duration(audio, rate, min_seconds=CFG.min_audio_seconds)
        timings["pad"] = (time.perf_counter() - t0) * 1000.0
        try:
            t0 = time.perf_counter()
            txn = transcribe(padded, rate)
            timings["stt_total"] = (time.perf_counter() - t0) * 1000.0
            timings["stt_encode"] = txn.encode_ms
            timings["stt_request"] = txn.request_ms
        except Exception as e:
            logger.exception("STT failed")
            if CFG.enable_toasts:
                toast("Whisper Dictate — STT error", str(e)[:200])
            return
        logger.info("stt lang=%r bytes=%d text=%r", txn.language, txn.audio_bytes, txn.text)
        if not txn.text.strip():
            return

        # Raw mode: skip the LLM entirely; paste the Whisper transcript as-is.
        if CFG.polish_mode == "raw":
            logger.info("raw mode: skipping LLM")
            t0 = time.perf_counter()
            paste_text(
                txn.text,
                restore_clipboard=CFG.restore_clipboard,
                restore_delay=CFG.clipboard_restore_delay,
            )
            timings["paste"] = (time.perf_counter() - t0) * 1000.0
        else:
            instruction = CFG.polish_modes.get(CFG.polish_mode, "")
            t0 = time.perf_counter()
            try:
                thinking_budget = 0 if CFG.disable_gemini_thinking else None
                polished = polish(txn.text, txn.language, instruction, thinking_budget)
            except Exception as e:
                logger.exception("LLM polish failed")
                if CFG.enable_toasts:
                    toast("Whisper Dictate — LLM error", str(e)[:200])
                polished = txn.text  # fall back to raw transcript
            finally:
                timings["polish"] = (time.perf_counter() - t0) * 1000.0
            logger.info("polished (mode=%s)=%r", CFG.polish_mode, polished)
            if polished:
                t0 = time.perf_counter()
                paste_text(
                    polished,
                    restore_clipboard=CFG.restore_clipboard,
                    restore_delay=CFG.clipboard_restore_delay,
                )
                timings["paste"] = (time.perf_counter() - t0) * 1000.0
    except Exception:
        logger.exception("pipeline crashed")
        traceback.print_exc()
    finally:
        timings["total"] = stop_ms + (time.perf_counter() - pipeline_t0) * 1000.0
        logger.info("pipeline timing: %s", _timing_summary(timings))
        _set_state("idle")
        _processing_lock.release()


def _stop_and_process(reason: str) -> None:
    """Centralized stop path: stops recorder, kicks processing."""
    global _recording
    with _recording_lock:
        if not _recording:
            return
        _recording = False
    t0 = time.perf_counter()
    audio, rate = _recorder.stop()
    stop_ms = (time.perf_counter() - t0) * 1000.0
    dur = audio.size / rate
    logger.info("record stop [%s] (%.2fs @ %dHz, stop=%.0fms)", reason, dur, rate, stop_ms)
    threading.Thread(target=_process, args=(audio, rate, stop_ms), daemon=True).start()


def _on_press(key):
    global _recording
    if key != PTT_KEY:
        return
    logger.debug("on_press PTT (recording=%s)", _recording)
    with _recording_lock:
        if _recording:
            return
        _recording = True
    # Pre-flight mic check: if muted, try to unmute. If we still can't unmute
    # (hardware mute switch, no permission, mic_control failed to init), show
    # the "muted" overlay state and skip recording — otherwise we'd waste
    # an API call producing Whisper's "Thank you" hallucination.
    mc = get_mic_control()
    if mc.is_muted() is True:
        ok, msg = mc.ensure_unmuted(0.6)
        logger.info("mic unmute on press: ok=%s %s", ok, msg)
        if not ok:
            logger.warning("mic is muted and cannot be unmuted — skipping recording")
            with _recording_lock:
                _recording = False
            _set_state("muted")
            return
    logger.info("record start")
    _set_state("recording")
    try:
        _recorder.start()
    except Exception as e:
        logger.exception("recorder.start failed")
        with _recording_lock:
            _recording = False
        _set_state("idle")
        if CFG.enable_toasts:
            toast("Whisper Dictate — mic error", f"Couldn't open device: {e}"[:200])
        return


def _on_release(key):
    if key != PTT_KEY:
        return
    logger.debug("on_release PTT (recording=%s)", _recording)
    _stop_and_process(reason="key_release")


def _on_quit() -> None:
    logger.info("quit requested")
    if _listener is not None:
        _listener.stop()
    if _overlay is not None:
        _overlay.stop()
    # Tray.run blocks in its own thread; calling icon.stop() ends that loop.
    if _tray is not None:
        try:
            _tray.stop()
        except Exception:
            pass
    # Quit Qt event loop on the main thread.
    if _qt_app is not None:
        try:
            QMetaObject.invokeMethod(_qt_app, "quit", Qt.QueuedConnection)
        except Exception:
            pass


def _persist_mic_device(idx: int | None) -> None:
    """Write mic_device back into config.toml, preserving other lines."""
    path = cfg_mod.CONFIG_PATH
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    new_line = "# mic_device = 0  # using system default" if idx is None else f"mic_device = {idx}"
    pattern = re.compile(r"^(?:#\s*)?mic_device\s*=\s*[^\n]*", re.MULTILINE)
    if pattern.search(content):
        content = pattern.sub(new_line, content, count=1)
    else:
        content = content.rstrip() + f"\n{new_line}\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _on_select_device(idx: int | None) -> None:
    """Tray callback: switch the recorder's input device and persist the choice."""
    logger.info("device switch -> %s", idx)
    _recorder.device = idx
    try:
        _persist_mic_device(idx)
    except Exception:
        logger.exception("failed to persist mic_device")


def _persist_polish_mode(mode: str) -> None:
    """Write polish_mode back into config.toml, preserving other lines."""
    path = cfg_mod.CONFIG_PATH
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    new_line = f'polish_mode = "{mode}"'
    pattern = re.compile(r"^(?:#\s*)?polish_mode\s*=\s*[^\n]*", re.MULTILINE)
    if pattern.search(content):
        content = pattern.sub(new_line, content, count=1)
    else:
        content = content.rstrip() + f"\n{new_line}\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _on_select_polish_mode(mode: str) -> None:
    """Tray callback: switch the active polish mode and persist."""
    valid = set(CFG.polish_modes.keys()) | {"raw"}
    if mode not in valid:
        return
    logger.info("polish_mode switch -> %s", mode)
    CFG.polish_mode = mode
    try:
        _persist_polish_mode(mode)
    except Exception:
        logger.exception("failed to persist polish_mode")


def main() -> int:
    global _tray, _overlay, _listener, _qt_app
    for var in ("GROQ_API_KEY", "GOOGLE_API_KEY"):
        if not os.environ.get(var):
            msg = f"{var} not set in .env"
            print(f"error: {msg}", file=sys.stderr)
            logger.error(msg)
            return 1

    # Qt event loop MUST run on the main thread on Windows. Create the QApplication
    # here and run app.exec() at the end. The tray (pystray) moves to a worker thread.
    _qt_app = QApplication.instance() or QApplication(sys.argv)
    _qt_app.setQuitOnLastWindowClosed(False)  # closing the overlay must not quit the app

    _overlay = Overlay()

    _listener = keyboard.Listener(on_press=_on_press, on_release=_on_release)
    _listener.start()
    logger.info("started (hotkey=%s, mic_device=%s)", CFG.hotkey, CFG.mic_device)
    print(f"Whisper Dictate ready. Hold {CFG.hotkey} to dictate. Right-click tray icon to quit.")

    # Build ordered list of (key, label) for the Polish-mode submenu.
    # "raw" always appears even if user removed it from polish_modes.
    polish_mode_keys = list(CFG.polish_modes.keys()) + ["raw"]
    polish_mode_items = [
        (k, cfg_mod.POLISH_MODE_LABELS.get(k, k.replace("_", " ").title()))
        for k in polish_mode_keys
    ]

    _tray = Tray(
        on_quit=_on_quit,
        current_device=CFG.mic_device,
        on_select_device=_on_select_device,
        current_polish_mode=CFG.polish_mode,
        polish_mode_items=polish_mode_items,
        on_select_polish_mode=_on_select_polish_mode,
        show_all_backends=CFG.show_all_backends,
    )
    # Tray runs its Win32 message pump in a daemon thread.
    threading.Thread(target=_tray.run, daemon=True, name="tray-msgpump").start()

    _qt_app.exec()  # blocks until QApplication.quit()
    logger.info("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
