"""Probe the new Recorder against device 43. Start, sleep 3s, stop, report peak."""
import time
import numpy as np
from audio import Recorder, SAMPLE_RATE

print("Recording 3s from device 43 via new Recorder — SPEAK NOW")
r = Recorder(device=43)
r.start()
time.sleep(3.0)
audio = r.stop()
peak = float(np.max(np.abs(audio))) if audio.size else 0.0
print(f"samples={audio.size}  duration={audio.size/SAMPLE_RATE:.2f}s  peak={peak:.4f}")
if peak > 0.01:
    print("OK — Recorder works.")
else:
    print("STILL SILENT — different fix needed.")
