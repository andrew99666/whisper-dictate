"""Post-processing via Gemini 3.5 Flash: clean fillers, fix grammar, clarify, preserve language."""
from __future__ import annotations

import os
from google import genai
from google.genai import types

MODEL_ID = "gemini-3.1-flash-lite"

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


def polish(raw_transcript: str, detected_language: str = "", system_instruction: str = "") -> str:
    """Clean up a transcript. detected_language is a hint (e.g. 'English', 'Russian').

    If system_instruction is non-empty, it overrides the built-in default.
    """
    if not raw_transcript.strip():
        return ""

    user_msg = raw_transcript
    if detected_language:
        # Hint helps when transcript is very short / ambiguous
        user_msg = f"[Detected language: {detected_language}]\n\n{raw_transcript}"

    instruction = system_instruction.strip() or SYSTEM_INSTRUCTION
    client = _get_client()
    resp = client.models.generate_content(
        model=MODEL_ID,
        contents=user_msg,
        config=types.GenerateContentConfig(
            system_instruction=instruction,
            temperature=0.2,
            max_output_tokens=2048,
        ),
    )
    text = (resp.text or "").strip()
    # Fallback: lite models occasionally return empty for trivial inputs ("okay", "yes").
    # Return the raw transcript so the user isn't left with nothing pasted.
    if not text:
        return raw_transcript.strip()
    return text
