"""Probe device 23 with various (rate, channels, dtype) combos to find one that opens."""
import time
import numpy as np
import sounddevice as sd

DEV = 23
info = sd.query_devices(DEV)
print(f"Device {DEV}: {info['name']!r}")
print(f"  default_samplerate: {info['default_samplerate']}")
print(f"  max_input_channels: {info['max_input_channels']}")

combos = []
for rate in [int(info["default_samplerate"]), 48000, 44100, 16000]:
    for ch in [1, 2]:
        for dtype in ["float32", "int16"]:
            combos.append((rate, ch, dtype))

for rate, ch, dt in combos:
    try:
        sd.check_input_settings(device=DEV, samplerate=rate, channels=ch, dtype=dt)
        ok_check = True
    except Exception as e:
        ok_check = False
        # Skip combos that fail static check
        continue
    try:
        buf = sd.rec(int(0.5 * rate), samplerate=rate, channels=ch, dtype=dt, device=DEV)
        sd.wait()
        peak = float(np.max(np.abs(buf.astype('float32')))) if buf.size else 0.0
        print(f"  rate={rate:>5} ch={ch} dt={dt}  -> OK  peak={peak:.4f}")
    except Exception as e:
        print(f"  rate={rate:>5} ch={ch} dt={dt}  -> FAIL: {type(e).__name__}: {str(e)[:80]}")
