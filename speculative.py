"""Prepare dictation during quiet tails; never reuse results after new speech."""
from __future__ import annotations

from concurrent.futures import Future
from dataclasses import dataclass
import logging
import threading
import time

import numpy as np
import webrtcvad

from audio import pad_to_min_duration
from llm import polish
from stt import Transcription, transcribe

_logger = logging.getLogger("whisper-dictate")
_slots = threading.BoundedSemaphore(2)


@dataclass(frozen=True)
class PreparedDictation:
    transcription: Transcription
    text: str
    revision: int
    frames: int
    started_at: float
    finished_at: float
    stt_ms: float
    polish_ms: float


class StalePreparation(Exception):
    pass


class SpeculativeSession:
    def __init__(self, mode: str, instruction: str, min_audio_seconds: float = 1.0,
                 quiet_seconds: float = 0.08, min_spacing_seconds: float = 0.75):
        self.mode = mode
        self.instruction = instruction
        self.min_audio_seconds = min_audio_seconds
        self.quiet_seconds = quiet_seconds
        self.min_spacing_seconds = min_spacing_seconds
        self._lock = threading.Lock()
        self._vad = webrtcvad.Vad(0)
        self._chunks = []
        self._pending = np.zeros(0, dtype=np.float32)
        self._frames = 0
        self._processed_frames = 0
        self._last_active_frame = 0
        self._last_submitted_frame = -1
        self._revision = 0
        self._submitted_revision = -1
        self._future = None
        self._future_frames = 0
        self._rate = None
        self._has_signal = False
        self._disabled = False
        self.requests = 0

    def push(self, chunk: np.ndarray, rate: int) -> None:
        # Called on the capture callback. The RPC always runs in a daemon worker.
        with self._lock:
            if self._disabled or rate not in (8000, 16000, 32000, 48000):
                self._disabled = True
                return
            if self._rate is not None and rate != self._rate:
                self._disabled = True
                return
            self._rate = rate
            mono = chunk.reshape(-1)
            self._chunks.append(mono)
            self._frames += mono.size
            peak = float(np.max(np.abs(mono))) if mono.size else 0.0
            self._has_signal = self._has_signal or peak >= 0.005
            if peak >= 0.003:
                self._revision += 1
                self._last_active_frame = self._frames
            pending = np.concatenate((self._pending, mono))
            frame_size = rate // 50
            offset = 0
            while offset + frame_size <= pending.size:
                frame = pending[offset:offset + frame_size]
                pcm = (np.clip(frame, -1, 1) * 32767).astype(np.int16).tobytes()
                voiced = self._vad.is_speech(pcm, rate)
                self._processed_frames += frame_size
                if voiced and float(np.max(np.abs(frame))) >= 0.0005:
                    self._revision += 1
                    self._last_active_frame = max(self._last_active_frame, self._processed_frames)
                offset += frame_size
            self._pending = pending[offset:]
            quiet = (self._frames - self._last_active_frame) / rate
            spaced = (self._last_submitted_frame < 0 or
                      (self._frames - self._last_submitted_frame) / rate >= self.min_spacing_seconds)
            if (not self._has_signal or quiet < self.quiet_seconds or not spaced or
                    self._submitted_revision == self._revision or not _slots.acquire(blocking=False)):
                return
            revision = self._revision
            frames = self._frames
            chunks = tuple(self._chunks)
            future = Future()
            self._future = future
            self._future_frames = frames
            self._submitted_revision = revision
            self._last_submitted_frame = frames
            self.requests += 1
            threading.Thread(target=self._run, args=(future, chunks, rate, revision, frames),
                             daemon=True, name="dictation-prepare").start()

    def _run(self, future, chunks, rate, revision, frames):
        start = time.perf_counter()
        try:
            future.set_running_or_notify_cancel()
            waveform = np.concatenate(chunks).astype(np.float32, copy=False)
            waveform = pad_to_min_duration(waveform, rate, self.min_audio_seconds)
            txn = transcribe(waveform, rate)
            stt_ms = (time.perf_counter() - start) * 1000
            with self._lock:
                if self._disabled or revision != self._revision:
                    raise StalePreparation("New speech followed the prepared transcript")
            polish_start = time.perf_counter()
            text = txn.text if self.mode == "raw" else polish(txn.text, txn.language, self.instruction)
            end = time.perf_counter()
            future.set_result(PreparedDictation(txn, text, revision, frames, start, end,
                                               stt_ms, (end - polish_start) * 1000))
        except Exception as exc:
            future.set_exception(exc)
            if not isinstance(exc, StalePreparation):
                _logger.warning("dictation preparation failed: %s", type(exc).__name__)
        finally:
            _slots.release()

    def candidate(self, audio: np.ndarray, rate: int, mode: str, instruction: str) -> Future | None:
        with self._lock:
            if (self._disabled or self._future is None or self._rate != rate or
                    self._frames != audio.size or mode != self.mode or instruction != self.instruction or
                    self._submitted_revision != self._revision):
                return None
            # Reject even a partial quiet/voiced frame beyond the prepared snapshot.
            tail = audio.reshape(-1)[self._future_frames:]
            if tail.size and float(np.max(np.abs(tail))) >= 0.0005:
                return None
            return self._future

    def disable(self):
        with self._lock:
            self._disabled = True
