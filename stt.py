"""Speech-to-text via Groq's whisper-large-v3-turbo, with auto language detection."""
from __future__ import annotations

import os
from dataclasses import dataclass

from groq import Groq

from audio import to_flac_bytes
import numpy as np

MODEL_ID = "whisper-large-v3-turbo"


@dataclass
class Transcription:
    text: str
    language: str  # ISO code Whisper returned, e.g. "en", "ru"


_client: Groq | None = None


def _get_client() -> Groq:
    global _client
    if _client is None:
        _client = Groq(api_key=os.environ["GROQ_API_KEY"])
    return _client


def transcribe(audio: np.ndarray, sample_rate: int = 16_000) -> Transcription:
    """Send audio buffer to Groq Whisper as FLAC (smaller upload, lossless). Auto-detect language."""
    flac_bytes = to_flac_bytes(audio, sample_rate)
    client = _get_client()
    resp = client.audio.transcriptions.create(
        file=("audio.flac", flac_bytes, "audio/flac"),
        model=MODEL_ID,
        response_format="verbose_json",  # includes detected language
        temperature=0.0,
    )
    text = (getattr(resp, "text", "") or "").strip()
    language = getattr(resp, "language", "") or ""
    return Transcription(text=text, language=language)


def transcribe_wav_file(path: str) -> Transcription:
    """Convenience: transcribe an existing wav file from disk."""
    with open(path, "rb") as f:
        wav_bytes = f.read()
    client = _get_client()
    resp = client.audio.transcriptions.create(
        file=(os.path.basename(path), wav_bytes, "audio/wav"),
        model=MODEL_ID,
        response_format="verbose_json",
        temperature=0.0,
    )
    text = (getattr(resp, "text", "") or "").strip()
    language = getattr(resp, "language", "") or ""
    return Transcription(text=text, language=language)
