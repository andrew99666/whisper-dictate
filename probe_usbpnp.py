"""Probe USB PnP mic specifically with sd.rec (the path that works for BT HFP).

Run this while speaking continuously into the USB PnP mic for ~10 seconds.
"""
import time
import numpy as np
import sounddevice as sd

CANDIDATES = [
    (1,  "USB PnP MME"),
    (10, "USB PnP DirectSound"),
    (23, "USB PnP WASAPI"),
]

print("Speak CONTINUOUSLY into the USB PnP mic for the next 12 seconds.")
print("(Count out loud: one, two, three, four, five, six, seven, eight, ...)")
print()
time.sleep(0.5)

for dev, label in CANDIDATES:
    try:
        info = sd.query_devices(dev)
    except Exception as e:
        print(f"[{dev}] {label}  query failed: {e}")
        continue
    sr = int(info.get("default_samplerate") or 16000)
    print(f"[{dev}] {label}  -- recording 3s at {sr}Hz")
    try:
        buf = sd.rec(int(3 * sr), samplerate=sr, channels=1, dtype='float32',
                     device=dev, blocking=True)
        a = buf.flatten()
        peak = float(np.max(np.abs(a)))
        rms = float(np.sqrt(np.mean(a**2)))
        verdict = "OK" if peak > 0.01 else "SILENT"
        print(f"      peak={peak:.4f}  rms={rms:.4f}  => {verdict}")
    except Exception as e:
        print(f"      ERROR: {type(e).__name__}: {e}")
    print()
