"""Thread-isolated mic mute control.

pycaw's COM objects historically crashed the app with access violations
when garbage-collected in arbitrary worker threads (comtypes
IUnknown.Release running in a thread without proper COM apartment).
Multiple attempts to fix it in-place failed — every stress test still
produced "Exception ignored in __del__" access violations.

Fix: every pycaw / comtypes call happens in ONE dedicated daemon
thread that calls CoInitialize once at startup and holds the
IAudioEndpointVolume reference for the entire process lifetime. COM
objects are never released cross-thread, never garbage-collected, never
escape into general GC. Other threads submit commands via a Queue and
get results back via a per-request reply queue.

Public API:
    mc = get_mic_control()
    state = mc.is_muted()              # True | False | None (on init failure)
    ok, msg = mc.ensure_unmuted(0.6)   # tries to unmute + raise vol if low
"""
from __future__ import annotations

import logging
import queue
import threading
from typing import Any

_logger = logging.getLogger("whisper-dictate")


class _MicControl:
    def __init__(self) -> None:
        self._cmd_q: "queue.Queue[Any]" = queue.Queue()
        self._ready = threading.Event()
        self._init_error: Exception | None = None
        self._thread = threading.Thread(target=self._run, daemon=True, name="mic-control")
        self._thread.start()
        # Wait briefly for COM init + endpoint lookup to complete
        self._ready.wait(timeout=4.0)
        if self._init_error is not None:
            _logger.warning("mic_control init failed: %r", self._init_error)

    def _run(self) -> None:
        # ALL pycaw/comtypes use happens in this thread, from start to thread exit.
        try:
            import comtypes
            comtypes.CoInitialize()
        except Exception as e:
            self._init_error = e
            self._ready.set()
            return

        vol = None
        try:
            from ctypes import cast, POINTER
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            import warnings

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")  # silence pycaw COMError noise
                mic = AudioUtilities.GetMicrophone()
            interface = mic.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            vol = cast(interface, POINTER(IAudioEndpointVolume))
            # mic / interface / vol are now held in locals; vol is captured into
            # the command loop below and lives for the thread's entire lifetime.
        except Exception as e:
            self._init_error = e
            self._ready.set()
            return

        self._ready.set()

        while True:
            try:
                cmd = self._cmd_q.get()
            except Exception:
                continue
            if cmd is None:
                break
            name, args, reply = cmd
            try:
                if name == "get_mute":
                    reply.put(("ok", bool(vol.GetMute())))
                elif name == "ensure_unmuted":
                    min_vol = float(args[0])
                    was_muted = bool(vol.GetMute())
                    if was_muted:
                        vol.SetMute(0, None)
                    cur_vol = float(vol.GetMasterVolumeLevelScalar())
                    if cur_vol < min_vol:
                        vol.SetMasterVolumeLevelScalar(min_vol, None)
                    final_vol = float(vol.GetMasterVolumeLevelScalar())
                    # Verify the unmute actually stuck — some apps / hardware
                    # mute switches don't honor SetMute.
                    still_muted = bool(vol.GetMute())
                    reply.put(("ok", {
                        "was_muted": was_muted,
                        "still_muted": still_muted,
                        "vol": final_vol,
                    }))
                else:
                    reply.put(("err", f"unknown command {name!r}"))
            except Exception as e:
                reply.put(("err", f"{type(e).__name__}: {e}"))

    def _call(self, name: str, *args, timeout: float = 1.0) -> tuple[str, Any]:
        if self._init_error is not None:
            return "err", "mic_control not initialized"
        reply: "queue.Queue[Any]" = queue.Queue(maxsize=1)
        self._cmd_q.put((name, args, reply))
        try:
            return reply.get(timeout=timeout)
        except queue.Empty:
            return "err", "mic_control timeout"

    def is_muted(self) -> bool | None:
        status, value = self._call("get_mute")
        if status == "ok":
            return bool(value)
        return None

    def ensure_unmuted(self, min_volume: float = 0.6) -> tuple[bool, str]:
        """Try to unmute the default mic. Returns (success, message).

        success=False if mic_control unavailable, the call timed out, OR the
        mic remains muted after SetMute (hardware mute switch).
        """
        status, value = self._call("ensure_unmuted", min_volume)
        if status != "ok":
            return False, str(value)
        info = value
        if info["still_muted"]:
            return False, f"still muted after SetMute (hardware mute?) vol={info['vol']:.2f}"
        return True, f"was_muted={info['was_muted']} vol={info['vol']:.2f}"


_instance: _MicControl | None = None
_lock = threading.Lock()


def get_mic_control() -> _MicControl:
    """Lazily initialize the singleton mic control worker."""
    global _instance
    with _lock:
        if _instance is None:
            _instance = _MicControl()
    return _instance
