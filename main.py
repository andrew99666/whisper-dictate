"""Whisper Dictate — push-to-talk voice dictation for Windows.

Hold the configured hotkey (default: Right Ctrl) to record. Release to transcribe
(Groq Whisper), polish (Gemini), and paste into the focused window.
"""
from __future__ import annotations

import faulthandler
import logging
import os
import re
import sys
import threading
import traceback

import comtypes  # for CoInitialize in worker threads (pycaw COM finalizer safety)

from dotenv import load_dotenv
load_dotenv()

from pynput import keyboard
from PySide6.QtCore import QMetaObject, Qt
from PySide6.QtWidgets import QApplication

import config as cfg_mod
from audio import Recorder, SAMPLE_RATE, pad_to_min_duration
from stt import transcribe
from llm import polish, polish_stream
from paste import paste_text, type_text, type_stream
from tray import Tray
from feedback import setup_logging, toast
from mic_control import unmute_default_mic
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


def _process(audio, rate: int) -> None:
    """STT -> polish -> paste. Runs in a worker thread."""
    # pycaw (our mic-unmute) creates COM objects on the listener thread. Python's
    # GC may finalize them in this worker thread when it runs (e.g. during a lazy
    # import inside Groq's client). Without CoInitialize, comtypes IUnknown.Release()
    # crashes with an access violation. Initializing COM here makes finalizers safe.
    try:
        comtypes.CoInitialize()
    except Exception:
        pass
    if not _processing_lock.acquire(blocking=False):
        logger.info("dropped utterance: previous pipeline still running")
        return
    try:
        _set_state("processing")
        padded = pad_to_min_duration(audio, rate, min_seconds=CFG.min_audio_seconds)
        try:
            txn = transcribe(padded, rate)
        except Exception as e:
            logger.exception("STT failed")
            if CFG.enable_toasts:
                toast("Whisper Dictate — STT error", str(e)[:200])
            return
        logger.info("stt lang=%r text=%r", txn.language, txn.text)
        if not txn.text.strip():
            return

        # Raw mode: skip the LLM entirely; output the Whisper transcript as-is.
        if CFG.polish_mode == "raw":
            logger.info("raw mode: skipping LLM (output_mode=%s)", CFG.output_mode)
            if CFG.output_mode == "type":
                type_text(txn.text)
            else:
                paste_text(txn.text)
        elif CFG.output_mode == "type":
            # Stream the polish — characters appear as Gemini generates them.
            instruction = CFG.polish_modes.get(CFG.polish_mode, "")
            full_text = ""
            try:
                stream = polish_stream(txn.text, txn.language, instruction)
                full_text = type_stream(stream)
            except Exception as e:
                logger.exception("LLM streaming failed")
                if CFG.enable_toasts:
                    toast("Whisper Dictate — LLM error", str(e)[:200])
                # Only fall back to raw if nothing was typed yet; if some text
                # was typed before the failure, leave it — typing the raw on top
                # would duplicate content.
                if not full_text:
                    type_text(txn.text)
                    full_text = txn.text
            else:
                # Empty stream (lite model occasionally yields nothing) — fall back.
                if not full_text.strip():
                    type_text(txn.text)
                    full_text = txn.text
            logger.info("polished (streamed, mode=%s)=%r", CFG.polish_mode, full_text)
        else:
            # Paste mode: full polish, single Ctrl+V.
            instruction = CFG.polish_modes.get(CFG.polish_mode, "")
            try:
                polished = polish(txn.text, txn.language, instruction)
            except Exception as e:
                logger.exception("LLM polish failed")
                if CFG.enable_toasts:
                    toast("Whisper Dictate — LLM error", str(e)[:200])
                polished = txn.text
            logger.info("polished (mode=%s)=%r", CFG.polish_mode, polished)
            if polished:
                paste_text(polished)
    except Exception:
        logger.exception("pipeline crashed")
        traceback.print_exc()
    finally:
        _set_state("idle")
        _processing_lock.release()


def _stop_and_process(reason: str) -> None:
    """Centralized stop path: stops recorder, kicks processing."""
    global _recording
    with _recording_lock:
        if not _recording:
            return
        _recording = False
    audio, rate = _recorder.stop()
    dur = audio.size / rate
    logger.info("record stop [%s] (%.2fs @ %dHz)", reason, dur, rate)
    threading.Thread(target=_process, args=(audio, rate), daemon=True).start()


def _on_press(key):
    global _recording
    if key != PTT_KEY:
        return
    logger.debug("on_press PTT (recording=%s)", _recording)
    with _recording_lock:
        if _recording:
            return
        _recording = True
    logger.info("record start")
    _set_state("recording")
    # Re-unmute on every press. Windows can re-mute the default mic across sleep,
    # device re-enumeration, or other apps' policies; auto_unmute_mic at startup
    # alone isn't enough for a long-running app.
    if CFG.auto_unmute_mic:
        try:
            unmute_default_mic(min_volume=CFG.min_mic_volume)
        except Exception:
            pass
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


def _persist_output_mode(mode: str) -> None:
    """Write output_mode back into config.toml, preserving other lines."""
    path = cfg_mod.CONFIG_PATH
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    new_line = f'output_mode = "{mode}"'
    pattern = re.compile(r"^(?:#\s*)?output_mode\s*=\s*[^\n]*", re.MULTILINE)
    if pattern.search(content):
        content = pattern.sub(new_line, content, count=1)
    else:
        content = content.rstrip() + f"\n{new_line}\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _on_select_output_mode(mode: str) -> None:
    """Tray callback: switch output mode (paste vs type) and persist the choice."""
    if mode not in ("paste", "type"):
        return
    logger.info("output_mode switch -> %s", mode)
    CFG.output_mode = mode
    try:
        _persist_output_mode(mode)
    except Exception:
        logger.exception("failed to persist output_mode")


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

    if CFG.auto_unmute_mic:
        ok, msg = unmute_default_mic(min_volume=CFG.min_mic_volume)
        logger.info("mic unmute: ok=%s %s", ok, msg)

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
        current_output_mode=CFG.output_mode,
        on_select_output_mode=_on_select_output_mode,
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
