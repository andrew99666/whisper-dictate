"""Probe device 43 two ways: blocking sd.rec() and callback-based InputStream."""
import time
import numpy as np
import sounddevice as sd

DEV = 43
print(f"Device {DEV}: {sd.query_devices(DEV)['name']!r}")
print(f"  default samplerate: {sd.query_devices(DEV)['default_samplerate']}")

# --- Test 1: blocking sd.rec() (what diagnose_mic.py used) ---
print("\n[blocking sd.rec] 2s — speak NOW")
a = sd.rec(int(2 * 16000), samplerate=16000, channels=1, dtype="float32", device=DEV)
sd.wait()
a = a.flatten()
print(f"  samples={a.size}  peak={float(np.max(np.abs(a))):.4f}")

# --- Test 2: callback InputStream (what main.py uses) ---
print("\n[callback InputStream] 2s — speak NOW")
chunks = []
callback_count = [0]
def cb(indata, frames, time_info, status):
    callback_count[0] += 1
    if status:
        print(f"  status: {status}")
    chunks.append(indata.copy())

stream = sd.InputStream(samplerate=16000, channels=1, dtype="float32", device=DEV, callback=cb)
stream.start()
time.sleep(2.0)
stream.stop()
stream.close()
print(f"  callbacks fired: {callback_count[0]}")
if chunks:
    b = np.concatenate(chunks).flatten()
    print(f"  samples={b.size}  peak={float(np.max(np.abs(b))):.4f}")
else:
    print(f"  NO CHUNKS — callback never fired")
