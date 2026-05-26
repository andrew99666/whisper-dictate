"""Whisper Dictate — push-to-talk voice dictation for Windows.

Hold the configured hotkey (default: Right Ctrl) to record. Release to transcribe
(Groq Whisper), polish (Gemini), and paste into the focused window.
"""
from __future__ import annotations

import os
import re
import sys
import threading
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
from paste import paste_text, type_text
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
_watchdog: threading.Timer | None = None
_processing_lock = threading.Lock()
_tray: Tray | None = None
_overlay: Overlay | None = None
_listener: keyboard.Listener | None = None
_qt_app: QApplication | None = None

# Safety cap: if we somehow miss a key release, force-stop after this long.
MAX_RECORDING_SECONDS = 60


def _set_state(state: str) -> None:
    if _tray is not None:
        _tray.set_state(state)
    if _overlay is not None:
        _overlay.set_state(state)


def _process(audio, rate: int) -> None:
    """STT -> polish -> paste. Runs in a worker thread."""
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
        try:
            polished = polish(txn.text, txn.language, CFG.custom_system_instruction)
        except Exception as e:
            logger.exception("LLM polish failed")
            if CFG.enable_toasts:
                toast("Whisper Dictate — LLM error", str(e)[:200])
            # Fall back to raw transcript so user isn't left with nothing
            polished = txn.text
        logger.info("polished=%r mode=%s", polished, CFG.output_mode)
        if polished:
            if CFG.output_mode == "type":
                type_text(polished)
            else:
                paste_text(polished)
    except Exception:
        logger.exception("pipeline crashed")
        traceback.print_exc()
    finally:
        _set_state("idle")
        _processing_lock.release()


def _stop_and_process(reason: str) -> None:
    """Centralized stop path: cancels watchdog, stops recorder, kicks processing."""
    global _recording, _watchdog
    with _recording_lock:
        if not _recording:
            return
        _recording = False
    if _watchdog is not None:
        _watchdog.cancel()
        _watchdog = None
    audio, rate = _recorder.stop()
    dur = audio.size / rate
    logger.info("record stop [%s] (%.2fs @ %dHz)", reason, dur, rate)
    threading.Thread(target=_process, args=(audio, rate), daemon=True).start()


def _watchdog_fire() -> None:
    logger.warning("watchdog fired: forcing stop after %ds (key release likely missed)",
                   MAX_RECORDING_SECONDS)
    _stop_and_process(reason="watchdog")


def _on_press(key):
    global _recording, _watchdog
    if key != PTT_KEY:
        return
    logger.debug("on_press PTT (recording=%s)", _recording)
    with _recording_lock:
        if _recording:
            return
        _recording = True
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
    _watchdog = threading.Timer(MAX_RECORDING_SECONDS, _watchdog_fire)
    _watchdog.daemon = True
    _watchdog.start()


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

    _tray = Tray(
        on_quit=_on_quit,
        current_device=CFG.mic_device,
        on_select_device=_on_select_device,
        current_output_mode=CFG.output_mode,
        on_select_output_mode=_on_select_output_mode,
        show_all_backends=CFG.show_all_backends,
    )
    # Tray runs its Win32 message pump in a daemon thread.
    threading.Thread(target=_tray.run, daemon=True, name="tray-msgpump").start()

    _qt_app.exec()  # blocks until QApplication.quit()
    logger.info("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
