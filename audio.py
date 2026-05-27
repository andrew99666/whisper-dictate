"""Microphone capture for push-to-talk dictation.

Uses sd.InputStream with a callback that appends chunks to a list. Memory
grows linearly with the actual recording duration (no pre-allocation cap),
so dictations of arbitrary length work — 1s ≈ 200KB, 1 hour ≈ 700MB at
48kHz mono float32.
"""
from __future__ import annotations

import io
import threading
import time
import wave
from math import gcd
import numpy as np
import sounddevice as sd
import soundfile as sf
from scipy import signal

SAMPLE_RATE = 16_000
CHANNELS = 1
DTYPE = "float32"


def resample(audio: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    """Anti-aliased polyphase resampling. Whisper runs at 16kHz internally —
    sending higher rate audio just wastes upload bandwidth."""
    if source_rate == target_rate or audio.size == 0:
        return audio
    g = gcd(source_rate, target_rate)
    up = target_rate // g
    down = source_rate // g
    return signal.resample_poly(audio, up, down).astype(audio.dtype, copy=False)


class Recorder:
    """Callback-driven InputStream; chunks accumulate in a list, concatenated on stop().

    No pre-allocated buffer, no duration cap. Records at the device's native sample
    rate (WASAPI refuses non-native rates); the caller resamples downstream.
    """

    def __init__(self, sample_rate: int = SAMPLE_RATE, device: int | None = None):
        self.requested_sample_rate = sample_rate
        self.device = device
        self._stream: sd.InputStream | None = None
        self._chunks: list[np.ndarray] = []
        self._chunks_lock = threading.Lock()
        self._actual_rate: int = sample_rate

    def _rate_for_device(self, device: int | None) -> int:
        """Native sample rate for a device, or requested rate for the default device."""
        if device is None:
            return self.requested_sample_rate
        try:
            info = sd.query_devices(device)
            native = int(info.get("default_samplerate") or 0)
            return native if native > 0 else self.requested_sample_rate
        except Exception:
            return self.requested_sample_rate

    def _on_audio(self, indata, frames, time_info, status) -> None:
        # PortAudio reuses the buffer between callbacks — copy or it gets overwritten.
        # NEVER let an exception escape into PortAudio's C callback — that's a
        # likely segfault source. Swallow everything.
        try:
            with self._chunks_lock:
                self._chunks.append(indata.copy())
        except Exception:
            pass

    def start(self) -> None:
        """Open an InputStream on the configured device; fall back to default on failure.

        WASAPI can intermittently fail with WDM-KS pin errors (GLE 0x490). Falling
        back to the system default (typically MME) is more forgiving.
        """
        with self._chunks_lock:
            self._chunks.clear()

        candidates: list[tuple[int | None, int]] = [
            (self.device, self._rate_for_device(self.device)),
        ]
        if self.device is not None:
            candidates.append((None, self._rate_for_device(None)))

        last_err: Exception | None = None
        for dev, rate in candidates:
            for attempt in range(2):
                try:
                    self._stream = sd.InputStream(
                        samplerate=rate,
                        channels=CHANNELS,
                        dtype=DTYPE,
                        device=dev,
                        callback=self._on_audio,
                    )
                    self._stream.start()
                    self._actual_rate = rate
                    return
                except Exception as e:
                    last_err = e
                    if self._stream is not None:
                        try:
                            self._stream.close()
                        except Exception:
                            pass
                        self._stream = None
                    time.sleep(0.15)
        assert last_err is not None
        raise last_err

    def stop(self) -> tuple[np.ndarray, int]:
        """Returns (audio, sample_rate). Caller uses the returned rate downstream.

        Closes the stream defensively: stop() then a short drain delay before
        close(). PortAudio's Windows backend can crash if close() races with an
        in-flight callback; the delay gives any pending callback time to return.
        """
        rate = self._actual_rate
        stream = self._stream
        self._stream = None  # detach first so the callback is harmless if it fires
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
            # Give the PortAudio callback thread time to fully drain before close().
            time.sleep(0.05)
            try:
                stream.close()
            except Exception:
                pass
        with self._chunks_lock:
            chunks = self._chunks
            self._chunks = []
        if not chunks:
            return np.zeros(0, dtype=np.float32), rate
        audio = np.concatenate(chunks, axis=0).flatten()
        return audio, rate


def pad_to_min_duration(audio: np.ndarray, sample_rate: int, min_seconds: float = 1.0) -> np.ndarray:
    """Pad with trailing silence so very short clips don't trip Whisper's segment minimum."""
    min_samples = int(min_seconds * sample_rate)
    if audio.size >= min_samples:
        return audio
    pad = np.zeros(min_samples - audio.size, dtype=audio.dtype)
    return np.concatenate([audio, pad])


def to_wav_bytes(audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> bytes:
    """Encode float32 mono audio as 16-bit PCM WAV bytes."""
    if audio.dtype != np.int16:
        clipped = np.clip(audio, -1.0, 1.0)
        pcm = (clipped * 32767.0).astype(np.int16)
    else:
        pcm = audio
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


def save_wav(audio: np.ndarray, path: str, sample_rate: int = SAMPLE_RATE) -> None:
    with open(path, "wb") as f:
        f.write(to_wav_bytes(audio, sample_rate))


def to_flac_bytes(audio: np.ndarray, sample_rate: int = SAMPLE_RATE,
                  target_rate: int | None = SAMPLE_RATE) -> bytes:
    """Encode mono audio as FLAC. If target_rate differs from sample_rate, resample first
    (sending 16kHz to Whisper instead of 48kHz cuts upload size ~6x)."""
    if target_rate is not None and target_rate != sample_rate:
        audio = resample(audio, sample_rate, target_rate)
        sample_rate = target_rate
    if audio.dtype != np.int16:
        clipped = np.clip(audio, -1.0, 1.0)
        pcm = (clipped * 32767.0).astype(np.int16)
    else:
        pcm = audio
    buf = io.BytesIO()
    sf.write(buf, pcm, sample_rate, format="FLAC", subtype="PCM_16")
    return buf.getvalue()
