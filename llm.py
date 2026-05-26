"""Post-processing via Gemini Flash-Lite: clean fillers, fix grammar, clarify, preserve language."""
from __future__ import annotations

import os
import queue
import threading
from typing import Iterator

from google import genai
from google.genai import types

MODEL_ID = "gemini-3.1-flash-lite"

# Streaming safety: if no chunk arrives within this many seconds, stop iterating.
# Gemini occasionally holds the HTTP stream open well past the final chunk;
# without this guard the pipeline stays in 'processing' for tens of seconds.
_STREAM_IDLE_TIMEOUT = 4.0

SYSTEM_INSTRUCTION = """You are a dictation post-processor. You receive a raw speech-to-text transcript and return a cleaned version.

Rules:
1. Remove filler words (um, uh, like, you know, эм, ну, типа, короче, etc.).
2. Fix grammar, punctuation, and capitalization.
3. If the speech is muddled, unclear, or rambling, rewrite it so a reader can understand it easily — but preserve the exact meaning. Never add facts, opinions, or information the speaker did not say.
4. Respond in the SAME LANGUAGE as the input. If the input is Russian, your output must be Russian. If the input is English, your output must be English. Never translate.
5. Output ONLY the cleaned text. No preamble, no quotes, no explanations, no commentary. If the input is empty or pure noise, return an empty string.
"""

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    return _client


def _build_user_msg(raw_transcript: str, detected_language: str) -> str:
    if detected_language:
        return f"[Detected language: {detected_language}]\n\n{raw_transcript}"
    return raw_transcript


def _gen_config(system_instruction: str) -> types.GenerateContentConfig:
    instruction = system_instruction.strip() or SYSTEM_INSTRUCTION
    return types.GenerateContentConfig(
        system_instruction=instruction,
        temperature=0.2,
        max_output_tokens=2048,
    )


def polish(raw_transcript: str, detected_language: str = "", system_instruction: str = "") -> str:
    """Clean up a transcript. detected_language is a hint (e.g. 'English', 'Russian').

    If system_instruction is non-empty, it overrides the built-in default.
    """
    if not raw_transcript.strip():
        return ""

    client = _get_client()
    resp = client.models.generate_content(
        model=MODEL_ID,
        contents=_build_user_msg(raw_transcript, detected_language),
        config=_gen_config(system_instruction),
    )
    text = (resp.text or "").strip()
    # Fallback: lite models occasionally return empty for trivial inputs ("okay", "yes").
    # Return the raw transcript so the user isn't left with nothing pasted.
    if not text:
        return raw_transcript.strip()
    return text


def polish_stream(raw_transcript: str, detected_language: str = "",
                  system_instruction: str = "") -> Iterator[str]:
    """Stream the polished text from Gemini, yielding chunks as they arrive.

    Includes a per-chunk idle timeout: if no chunk arrives for _STREAM_IDLE_TIMEOUT
    seconds, this generator stops yielding. The underlying producer thread keeps
    running as a daemon and exits when the process does. This guards against
    Gemini occasionally keeping the HTTP stream open well past the final chunk.

    Yields nothing if the input is empty / whitespace-only.
    """
    if not raw_transcript.strip():
        return

    client = _get_client()
    user_msg = _build_user_msg(raw_transcript, detected_language)
    config = _gen_config(system_instruction)

    q: "queue.Queue[object]" = queue.Queue()
    _SENTINEL = object()
    _ERROR = "__error__"

    def _producer() -> None:
        try:
            for chunk in client.models.generate_content_stream(
                model=MODEL_ID, contents=user_msg, config=config,
            ):
                text = chunk.text or ""
                if text:
                    q.put(text)
        except Exception as e:
            q.put((_ERROR, e))
        finally:
            q.put(_SENTINEL)

    threading.Thread(target=_producer, daemon=True, name="gemini-stream").start()

    while True:
        try:
            item = q.get(timeout=_STREAM_IDLE_TIMEOUT)
        except queue.Empty:
            # No chunk in too long — give up. Producer keeps running as daemon.
            return
        if item is _SENTINEL:
            return
        if isinstance(item, tuple) and len(item) == 2 and item[0] == _ERROR:
            raise item[1]
        yield item  # type: ignore[misc]
