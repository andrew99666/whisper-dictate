"""Probe: read mute/volume of default mic, unmute it, confirm."""
from ctypes import cast, POINTER
from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

# GetMicrophone returns a raw IMMDevice pointer (no FriendlyName attribute).
mic_imm = AudioUtilities.GetMicrophone()
interface = mic_imm.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
vol = cast(interface, POINTER(IAudioEndpointVolume))
print(f"  before: muted={bool(vol.GetMute())}  vol={vol.GetMasterVolumeLevelScalar():.2f}")
vol.SetMute(0, None)
print(f"  after:  muted={bool(vol.GetMute())}  vol={vol.GetMasterVolumeLevelScalar():.2f}")

# Also list all capture devices so we can match by name if needed
print("\nAll capture endpoints:")
for d in AudioUtilities.GetAllDevices():
    try:
        if d.state == 1:  # active
            print(f"  - {d.FriendlyName!r}  (id={d.id!r})")
    except Exception:
        pass
