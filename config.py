"""Load configuration from config.toml (optional) with sane defaults."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.toml")


# Built-in polish modes. Users can override any of these (or add new ones)
# by including a `[polish_modes]` table in config.toml.
DEFAULT_POLISH_MODES: dict[str, str] = {
    "default": (
        "You are a dictation post-processor. You receive a raw speech-to-text "
        "transcript and return a cleaned version.\n\n"
        "Rules:\n"
        "1. Remove filler words (um, uh, like, you know, эм, ну, типа, короче, etc.).\n"
        "2. Fix grammar, punctuation, and capitalization.\n"
        "3. If the speech is muddled, unclear, or rambling, rewrite it so a reader can "
        "understand it easily — but preserve the exact meaning. Never add facts, opinions, "
        "or information the speaker did not say.\n"
        "4. Respond in the SAME LANGUAGE as the input. If the input is Russian, your output "
        "must be Russian. If the input is English, your output must be English. Never translate.\n"
        "5. Output ONLY the cleaned text. No preamble, no quotes, no explanations, no "
        "commentary. If the input is empty or pure noise, return an empty string."
    ),
    "email": (
        "You are a dictation post-processor for email composition. The speaker is dictating "
        "an email body. Format the transcript as clean email text.\n\n"
        "Rules:\n"
        "1. Remove filler words (um, uh, etc.). Fix grammar, punctuation, capitalization.\n"
        "2. PRESERVE everything the speaker said. If they dictated a greeting "
        "('Hi John', 'Hello team') or a sign-off ('Thanks, Andrew', 'Best regards'), KEEP "
        "those words and format them on their own lines as proper email greeting/closing. "
        "Never silently drop the speaker's content.\n"
        "3. Do NOT paraphrase. Keep the speaker's word choices and tone — change 'want' to "
        "'would like' only if the surrounding context is clearly formal. Light grammar "
        "edits only.\n"
        "4. Structure the body into paragraphs where natural; otherwise leave as a single "
        "block.\n"
        "5. Do NOT invent content: no greetings/sign-offs/recipient names/context that the "
        "speaker did not dictate. No filler phrases like 'please note that' or 'I hope this "
        "email finds you well'.\n"
        "6. Respond in the SAME LANGUAGE as the input. Never translate.\n"
        "7. Output ONLY the email body text. No subject line, no commentary, no markdown."
    ),
    "chat": (
        "You are a dictation post-processor for casual chat / instant messages. Clean the "
        "transcript into something suitable for sending in a chat.\n\n"
        "Rules:\n"
        "1. Remove filler words. Light grammar fixes only — enough to be readable, not so "
        "much that it sounds stiff.\n"
        "2. Keep it short, direct, and conversational. Don't over-formalize. Don't add "
        "complete sentences if the original was a fragment.\n"
        "3. Preserve meaning exactly. Never add content the speaker didn't say.\n"
        "4. Respond in the SAME LANGUAGE as the input. Never translate.\n"
        "5. Output ONLY the message text. No quotes, no commentary."
    ),
    "code": (
        "You are a dictation post-processor for technical and code-related content. The input "
        "is a verbal description of code, commands, file paths, or technical instructions.\n\n"
        "Rules:\n"
        "1. Preserve all technical terms, programming keywords, file paths, URLs, command "
        "names, and symbols exactly as spoken. Do not paraphrase technical content. "
        "For example, if the speaker says 'git push origin main', do NOT change it to "
        "'Git pushes origin to main'.\n"
        "2. If the speaker dictates symbols aloud (e.g. 'open paren x comma y close paren'), "
        "convert them to the literal characters (`(x, y)`).\n"
        "3. Light grammar/punctuation fixes only where they aid readability.\n"
        "4. Remove only obvious filler words ('um', 'uh'). Do not rephrase.\n"
        "5. Respond in the SAME LANGUAGE as the input. Never translate.\n"
        "6. Output ONLY the cleaned text. No code fences unless the speaker explicitly "
        "indicated them. No commentary."
    ),
    "translate_en": (
        "You are a dictation translator. The input is a raw speech-to-text transcript in any "
        "language. Return a clean, natural English translation.\n\n"
        "Rules:\n"
        "1. Translate to fluent, natural English regardless of the input language.\n"
        "2. Remove filler words and fix any grammar that survived translation.\n"
        "3. Preserve the speaker's meaning exactly. Never add content, opinions, or context "
        "the speaker didn't say.\n"
        "4. The output is ALWAYS in English, even if the input is already in English "
        "(in which case just clean it up as normal).\n"
        "5. Output ONLY the English text. No commentary, no quotes, no source-language note."
    ),
}

# Human-readable labels for the tray menu. "raw" is handled specially (skips the LLM).
POLISH_MODE_LABELS: dict[str, str] = {
    "default":      "Default",
    "email":        "Email",
    "chat":         "Chat",
    "code":         "Code",
    "translate_en": "Translate to English",
    "raw":          "Raw (no polish)",
}


@dataclass
class Config:
    hotkey: str = "ctrl_r"                 # pynput Key name (e.g. "ctrl_r", "f9", "menu")
    mic_device: int | None = None          # None = default device
    enable_toasts: bool = True
    log_path: str = "whisper-dictate.log"
    min_audio_seconds: float = 1.0
    show_all_backends: bool = False
    polish_mode: str = "default"           # active mode; "raw" skips LLM entirely
    polish_modes: dict[str, str] = field(default_factory=dict)  # populated from defaults + config.toml


def load(path: str = CONFIG_PATH) -> Config:
    cfg = Config()
    # Seed defaults first; config.toml can override individual keys.
    cfg.polish_modes = dict(DEFAULT_POLISH_MODES)
    if not os.path.exists(path):
        return cfg
    with open(path, "rb") as f:
        data = tomllib.load(f)
    for k, v in data.items():
        if not hasattr(cfg, k):
            continue
        if k == "polish_modes" and isinstance(v, dict):
            # Merge user-provided modes on top of defaults.
            cfg.polish_modes.update(v)
        else:
            setattr(cfg, k, v)
    return cfg
