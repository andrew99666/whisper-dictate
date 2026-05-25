"""Stage 1 PTT test: hold Right Ctrl to record, release to save to debug_ptt.wav.

Press Esc to quit.
"""
import os
import sys
import numpy as np
from pynput import keyboard

from audio import Recorder, SAMPLE_RATE, save_wav, pad_to_min_duration

OUT = os.path.join(os.path.dirname(__file__), "debug_ptt.wav")

rec = Recorder()
recording = False


def on_press(key):
    global recording
    if key == keyboard.Key.ctrl_r and not recording:
        recording = True
        print("REC...", flush=True)
        rec.start()
    elif key == keyboard.Key.esc:
        print("quit")
        return False


def on_release(key):
    global recording
    if key == keyboard.Key.ctrl_r and recording:
        recording = False
        audio = rec.stop()
        dur = audio.size / SAMPLE_RATE
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        print(f"stopped — {dur:.2f}s, peak={peak:.4f}", flush=True)
        padded = pad_to_min_duration(audio, SAMPLE_RATE, min_seconds=1.0)
        save_wav(padded, OUT)
        print(f"saved -> {OUT}", flush=True)


def main():
    print("Hold Right Ctrl to record, release to save. Esc to quit.", flush=True)
    with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
        listener.join()


if __name__ == "__main__":
    main()
