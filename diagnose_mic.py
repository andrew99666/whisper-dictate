"""List input devices and record 3s from the default, reporting signal levels."""
import time
import numpy as np
import sounddevice as sd

print("=== All audio devices ===")
print(sd.query_devices())
print()
print(f"=== Default devices ===")
print(f"Default input:  {sd.default.device[0]} -> {sd.query_devices(sd.default.device[0])['name']}")
print(f"Default output: {sd.default.device[1]} -> {sd.query_devices(sd.default.device[1])['name']}")
print()

print("=== Recording 3s from default input — speak loudly NOW ===")
audio = sd.rec(int(3 * 16000), samplerate=16000, channels=1, dtype="float32")
sd.wait()
audio = audio.flatten()
peak = float(np.max(np.abs(audio)))
rms = float(np.sqrt(np.mean(audio**2)))
print(f"Peak: {peak:.6f}   RMS: {rms:.6f}")
if peak < 0.001:
    print("=> SILENT. Mic isn't capturing. Check: Windows mic permissions, mic mute, correct default device.")
elif peak < 0.05:
    print("=> Very quiet. Mic might be muted/low gain, or wrong device.")
else:
    print("=> OK signal level.")

print()
print("=== Trying each input device (1s each) ===")
devices = sd.query_devices()
for i, d in enumerate(devices):
    if d["max_input_channels"] < 1:
        continue
    try:
        a = sd.rec(int(1.0 * 16000), samplerate=16000, channels=1, dtype="float32", device=i)
        sd.wait()
        a = a.flatten()
        p = float(np.max(np.abs(a)))
        print(f"  [{i:>2}] peak={p:.4f}  {d['name']!r}")
    except Exception as e:
        print(f"  [{i:>2}] ERROR: {type(e).__name__}: {e}  {d['name']!r}")
