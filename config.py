"""Load configuration from config.toml (optional) with sane defaults."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.toml")


@dataclass
class Config:
    hotkey: str = "ctrl_r"                 # pynput Key name (e.g. "ctrl_r", "f9", "menu")
    mic_device: int | None = None          # None = default device
    enable_beeps: bool = True
    enable_toasts: bool = True
    log_path: str = "whisper-dictate.log"
    custom_system_instruction: str = ""    # if set, overrides default LLM prompt
    min_audio_seconds: float = 1.0         # pad shorter clips with silence
    auto_unmute_mic: bool = True           # unmute the default input on startup
    min_mic_volume: float = 0.6            # raise mic volume to at least this if lower
    show_all_backends: bool = False        # tray menu: show every backend (MME/WASAPI/etc) instead of just WASAPI
    output_mode: str = "paste"             # "paste" (Ctrl+V) or "type" (char-by-char via SendInput)


def load(path: str = CONFIG_PATH) -> Config:
    cfg = Config()
    if not os.path.exists(path):
        return cfg
    with open(path, "rb") as f:
        data = tomllib.load(f)
    for k, v in data.items():
        if hasattr(cfg, k):
            setattr(cfg, k, v)
    return cfg
