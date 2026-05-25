"""Ensure the default input device is unmuted and at a usable volume on app start."""
from __future__ import annotations

import warnings
from ctypes import cast, POINTER
from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume


def unmute_default_mic(min_volume: float = 0.6) -> tuple[bool, str]:
    """Unmute the system default input device; raise volume to min_volume if lower.

    Returns (success, message). Never raises — returns (False, error) on failure
    so a flaky audio stack can't crash the app at startup.
    """
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # silence pycaw's COMError noise
            mic = AudioUtilities.GetMicrophone()
        interface = mic.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        vol = cast(interface, POINTER(IAudioEndpointVolume))
        was_muted = bool(vol.GetMute())
        prev_vol = vol.GetMasterVolumeLevelScalar()
        if was_muted:
            vol.SetMute(0, None)
        if prev_vol < min_volume:
            vol.SetMasterVolumeLevelScalar(min_volume, None)
        new_vol = vol.GetMasterVolumeLevelScalar()
        return True, f"was_muted={was_muted} vol {prev_vol:.2f} -> {new_vol:.2f}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
