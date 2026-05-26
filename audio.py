"""Microphone capture for push-to-talk dictation.

Uses sd.rec() (blocking-API path), not sd.InputStream(callback=...). On Windows,
some devices — particularly Bluetooth HFP headsets — only deliver audio data
through the blocking path; the callback API silently produces zero frames.
"""
from __future__ import annotations

import io
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
MAX_RECORD_SECONDS = 120  # generous PTT ceiling; trimmed on stop()


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
    """Pre-allocates a buffer and uses sd.rec() to fill it; stop() trims to actual duration.

    Records at the device's native sample rate (WASAPI refuses non-native rates).
    Whisper accepts any rate, so we pass the actual rate through to the encoder.
    """

    def __init__(self, sample_rate: int = SAMPLE_RATE, device: int | None = None,
                 max_seconds: int = MAX_RECORD_SECONDS):
        self.requested_sample_rate = sample_rate
        self.device = device
        self.max_seconds = max_seconds
        self._buffer: np.ndarray | None = None
        self._start_time: float | None = None
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

    def start(self) -> None:
        """Open the configured device; on persistent failure, fall back to the system default.

        WASAPI can fail with WDM-KS pin errors (GLE 0x490) when other audio activity
        in the process poisons the format negotiation. Falling back to the system
        default (MME) is more forgiving — Windows Audio Engine handles format conversion.
        """
        candidates: list[tuple[int | None, int]] = [
            (self.device, self._rate_for_device(self.device)),
        ]
        if self.device is not None:
            candidates.append((None, self._rate_for_device(None)))

        last_err: Exception | None = None
        for dev, rate in candidates:
            for attempt in range(2):
                try:
                    self._buffer = sd.rec(
                        int(self.max_seconds * rate),
                        samplerate=rate,
                        channels=CHANNELS,
                        dtype=DTYPE,
                        device=dev,
                    )
                    self._actual_rate = rate
                    self._start_time = time.monotonic()
                    return
                except Exception as e:
                    last_err = e
                    try:
                        sd.stop()
                    except Exception:
                        pass
                    time.sleep(0.15)
        assert last_err is not None
        raise last_err

    def stop(self) -> tuple[np.ndarray, int]:
        """Returns (audio, sample_rate). Caller uses the returned rate downstream."""
        if self._buffer is None or self._start_time is None:
            return np.zeros(0, dtype=np.float32), self.requested_sample_rate
        elapsed = time.monotonic() - self._start_time
        sd.stop()
        frames = min(int(elapsed * self._actual_rate), self._buffer.shape[0])
        audio = self._buffer[:frames].flatten().copy()
        rate = self._actual_rate
        self._buffer = None
        self._start_time = None
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
