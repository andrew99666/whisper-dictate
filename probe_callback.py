"""Probe several input devices with the SAME callback-based InputStream main.py uses.

Goal: find a device that actually delivers audio callbacks with sane values.
"""
import time
import numpy as np
import sounddevice as sd

CANDIDATES = [1, 22, 23, 24, 43, 46]

print("Each test: 3 seconds. Speak into the device you want to use during each test.")
print()

for dev in CANDIDATES:
    try:
        info = sd.query_devices(dev)
    except Exception as e:
        print(f"[{dev}] query_devices failed: {e}")
        continue
    name = info["name"]
    sr = int(info["default_samplerate"])
    api = sd.query_hostapis(info["hostapi"])["name"]

    print(f"[{dev}] {name!r}  ({api}, samplerate={sr})  -- SPEAK NOW")
    chunks = []
    cbs = [0]

    def cb(indata, frames, time_info, status):
        cbs[0] += 1
        chunks.append(indata.copy())

    try:
        # Use the device's native rate to avoid resampling-related issues
        stream = sd.InputStream(samplerate=sr, channels=1, dtype="float32",
                                device=dev, callback=cb)
        stream.start()
        time.sleep(3.0)
        stream.stop()
        stream.close()
    except Exception as e:
        print(f"   ERROR: {type(e).__name__}: {e}")
        continue

    if not chunks:
        print(f"   callbacks={cbs[0]}  NO DATA — callback API broken for this device")
        continue
    a = np.concatenate(chunks).flatten()
    peak = float(np.max(np.abs(a)))
    rms = float(np.sqrt(np.mean(a**2)))
    sane = -10.0 <= peak <= 10.0  # float32 audio should be in [-1, 1]
    verdict = "OK" if (sane and peak > 0.01) else ("GARBAGE" if not sane else "SILENT")
    print(f"   callbacks={cbs[0]}  samples={a.size}  peak={peak:.6g}  rms={rms:.6g}  => {verdict}")
    print()
