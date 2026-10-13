"""Microphone capture for push-to-talk dictation.

Uses sd.InputStream with a callback that appends chunks to a list. Memory
grows linearly with the actual recording duration (no pre-allocation cap),
so dictations of arbitrary length work — 1s ≈ 200KB, 1 hour ≈ 700MB at
48kHz mono float32.
"""
from __future__ import annotations

import io
import logging
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
_logger = logging.getLogger("whisper-dictate")


def _default_wasapi_input() -> int | None:
    """Use Windows' WASAPI default without persisting a volatile device index."""
    try:
        for api in sd.query_hostapis():
            if api.get("name") != "Windows WASAPI":
                continue
            device = int(api.get("default_input_device", -1))
            if device >= 0 and sd.query_devices(device, kind="input")["max_input_channels"] > 0:
                return device
    except Exception:
        pass
    return None


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

    def __init__(self, sample_rate: int = SAMPLE_RATE, device: int | None = None,
                 keep_stream_open: bool = True):
        self.requested_sample_rate = sample_rate
        self.device = device
        self.keep_stream_open = keep_stream_open
        self._stream: sd.InputStream | None = None
        self._chunks: list[np.ndarray] = []
        self._chunks_lock = threading.Lock()
        self._actual_rate: int = sample_rate
        self._capturing = False
        self._opened_device: int | None = None
        self._on_chunk = None

    def _rate_for_device(self, device: int | None) -> int:
        """Native sample rate for the selected or system-default input device."""
        try:
            info = sd.query_devices(device, kind="input")
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
                if self._capturing:
                    chunk = indata.copy()
                    self._chunks.append(chunk)
                    if self._on_chunk is not None:
                        try:
                            self._on_chunk(chunk, self._actual_rate)
                        except Exception:
                            self._on_chunk = None
        except Exception:
            pass

    def meter_level(self) -> float:
        """Read the latest captured block for UI only; never wait on the callback."""
        if not self._chunks_lock.acquire(blocking=False):
            return 0.0
        try:
            chunk = self._chunks[-1] if self._capturing and self._chunks else None
        finally:
            self._chunks_lock.release()
        if chunk is None or chunk.size == 0:
            return 0.0
        samples = chunk.reshape(-1)[::8]
        return float(np.sqrt(np.mean(samples * samples)))

    def start(self, on_chunk=None) -> None:
        """Open an InputStream on the configured device; fall back to default on failure.

        WASAPI can intermittently fail with WDM-KS pin errors (GLE 0x490). Falling
        back to the system default (typically MME) is more forgiving.
        """
        preferred = self.device if self.device is not None else _default_wasapi_input()
        if self._stream is not None:
            try:
                active = bool(self._stream.active)
            except Exception:
                active = False
            if self._opened_device == preferred and active:
                with self._chunks_lock:
                    self._chunks.clear()
                    self._on_chunk = on_chunk
                    self._capturing = True
                return
            self.close()
        with self._chunks_lock:
            self._chunks.clear()
            self._on_chunk = on_chunk
            self._capturing = True
        candidates: list[tuple[int | None, int]] = [
            (preferred, self._rate_for_device(preferred)),
        ]
        if preferred is not None:
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
                    self._actual_rate = rate
                    self._stream.start()
                    self._opened_device = dev
                    try:
                        info = sd.query_devices(dev, kind="input")
                        backend = sd.query_hostapis(info["hostapi"])["name"]
                        _logger.info("record input: device=%s name=%r backend=%r rate=%dHz",
                                     dev if dev is not None else "default", info["name"], backend, rate)
                    except Exception:
                        pass
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
        with self._chunks_lock:
            self._capturing = False
        raise last_err

    def stop(self) -> tuple[np.ndarray, int]:
        """Detach captured audio; retain the stream unless reuse is disabled."""
        rate = self._actual_rate
        with self._chunks_lock:
            self._capturing = False
            self._on_chunk = None
            chunks = self._chunks
            self._chunks = []
        if not self.keep_stream_open:
            self.close()
        if not chunks:
            return np.zeros(0, dtype=np.float32), rate
        audio = np.concatenate(chunks, axis=0).flatten()
        return audio, rate

    def close(self) -> None:
        """Close at quit/device change, preserving the PortAudio drain safeguard."""
        with self._chunks_lock:
            self._capturing = False
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
