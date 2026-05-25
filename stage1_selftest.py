"""Stage 1 self-test: programmatic 2s record, no PTT, just verifies the audio pipeline works.

Records 2 seconds from the default mic, saves debug_selftest.wav, prints stats.
"""
import os
import time
import wave
import numpy as np

from audio import Recorder, SAMPLE_RATE, save_wav, pad_to_min_duration

OUT = os.path.join(os.path.dirname(__file__), "debug_selftest.wav")


def main():
    print("Recording 2s from default mic (no input needed, just verifying pipeline)...")
    rec = Recorder()
    rec.start()
    time.sleep(2.0)
    audio = rec.stop()
    print(f"Captured {audio.size} samples ({audio.size / SAMPLE_RATE:.2f}s)")
    print(f"Peak amplitude: {np.max(np.abs(audio)):.4f}  RMS: {np.sqrt(np.mean(audio**2)):.4f}")

    padded = pad_to_min_duration(audio, SAMPLE_RATE, min_seconds=1.0)
    save_wav(padded, OUT)

    # Round-trip read to verify the file is a valid wav
    with wave.open(OUT, "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == SAMPLE_RATE
        frames = wf.getnframes()
    print(f"Wrote {OUT} ({frames} frames, {os.path.getsize(OUT)} bytes)")
    print("Stage 1 self-test PASS.")


if __name__ == "__main__":
    main()
