# Whisper Dictate — Push-to-Talk Voice Dictation for Windows

Free, open-source voice dictation for Windows. Hold a hotkey, speak, release — get clean text pasted into the focused app. A [Superwhisper](https://superwhisper.com) / [Wispr Flow](https://wisprflow.ai) alternative for Windows, built with [Groq Whisper Large v3 Turbo](https://console.groq.com/docs/model/whisper-large-v3-turbo) for transcription and [Gemini 3.5 Flash](https://ai.google.dev) for cleanup.

Auto-detects **English and Russian** per utterance (Whisper supports 99+ languages).

## Features

- **Push-to-talk hotkey** — hold Right Ctrl (configurable), speak, release. Transcribed in ~1–2 seconds.
- **Groq Whisper Large v3 Turbo** — fast cloud transcription at $0.04 per hour of audio.
- **Gemini 3.5 Flash polish** — strips filler words (`um`, `uh`, `ну`, `типа`), fixes grammar, rewrites for clarity, preserves the input language (no translation).
- **Auto-paste** into any app that accepts Ctrl+V. Your existing clipboard is saved and restored.
- **System tray** — pick your input microphone from a menu, see idle/recording/processing state at a glance.
- **Auto-unmute mic** on app start (prevents the "Whisper hallucinates 'thank you'" silent-mic failure mode).
- **Auto-start at login** (optional one-line PowerShell setup).
- **Bilingual transcription** — Russian and English on the same hotkey, language detected per utterance.

## Why

Polished dictation tools like Superwhisper and MacWhisper are macOS-only; Wispr Flow is a paid subscription. This is a small Python clone (~800 LOC) that does the same core job on Windows. You bring your own API keys; cost is negligible.

|  | Superwhisper | Wispr Flow | Whisper Dictate |
|---|---|---|---|
| Platform | macOS | macOS, Windows | Windows |
| Pricing | Subscription | Subscription | Free (BYO API keys) |
| Source available | No | No | Yes |
| Transcription | Local Whisper | Cloud | Groq Whisper Large v3 Turbo |
| LLM cleanup | Yes | Yes | Gemini 3.5 Flash |
| Custom prompts | Yes | Yes | Yes (edit `llm.py`) |

Typical cost: a few cents per day of heavy dictation.

## Install

Windows 10/11, Python 3.11+, a [Groq API key](https://console.groq.com/keys), and a [Google AI Studio key for Gemini](https://aistudio.google.com/app/apikey). Both have free tiers generous enough for personal use.

```powershell
git clone https://github.com/andrew99666/whisper-dictate.git
cd whisper-dictate
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Create `.env` in the project root:

```
GROQ_API_KEY=your_groq_key
GOOGLE_API_KEY=your_gemini_key
```

Run (no console window):

```powershell
.\.venv\Scripts\pythonw.exe main.py
```

Look for the gray circle in your system tray. Hold **Right Ctrl**, speak, release — text appears in whatever window has focus.

## Auto-start at login

```powershell
$startup = [Environment]::GetFolderPath("Startup")
$sc = (New-Object -ComObject WScript.Shell).CreateShortcut("$startup\WhisperDictate.lnk")
$sc.TargetPath = "$PWD\.venv\Scripts\pythonw.exe"
$sc.Arguments  = "$PWD\main.py"
$sc.WorkingDirectory = "$PWD"
$sc.Save()
```

To disable later: delete the shortcut, or toggle off in **Settings → Apps → Startup**.

## Configuration

All keys in `config.toml` are optional; defaults apply when absent.

```toml
hotkey = "ctrl_r"              # any pynput Key name: ctrl_r, ctrl_l, f9, menu, ...
# mic_device = 1               # tray menu also sets this; leave blank for system default
auto_unmute_mic = true
min_mic_volume = 0.6
enable_beeps = true
enable_toasts = true
show_all_backends = false      # tray menu: true = include MME/DirectSound/WDM-KS endpoints
```

The LLM polish prompt lives in [`llm.py`](llm.py) — edit `SYSTEM_INSTRUCTION` to add modes (format as bullet points, summarize, translate to English, etc.).

## How it works

```
Right Ctrl down  →  sounddevice.rec() into numpy buffer
Right Ctrl up    →  stop, trim to actual duration
                 →  POST audio (native sample rate) to Groq Whisper
                 →  POST transcript + detected language to Gemini 3.5 Flash
                 →  set clipboard, send Ctrl+V to focused window
                 →  restore previous clipboard
```

End-to-end latency: ~1.5–2.5 seconds from key release to paste.

## Troubleshooting

- **Whisper returns "Thank you" instead of my speech.** Your mic is sending silence. "Thank you" is Whisper's hallucination signature for empty audio (trained on lots of YouTube outros). Check Windows Sound Settings → Input → test mic level. The app auto-unmutes by default, but a hardware mute switch overrides this.
- **Nothing happens when I press the hotkey.** Check `whisper-dictate.log` for `PortAudioError`. The app retries and auto-falls back to the system default mic; if you see persistent WASAPI errors on a specific device, pick "System default" from the tray menu.
- **Only `v` is pasted, not the full text.** The Ctrl modifier didn't register in the target app. Increase the inter-key delay in `_send_paste_chord` (paste.py).
- **Bluetooth headphones drop to low-fi audio while recording.** Windows switches the BT profile to HFP for mic capture, and A2DP restoration after the mic is released is Windows-controlled and not always immediate. Use a USB or built-in mic for dictation — the BT headset can keep playing music in A2DP.

## Tech

Python 3.12 · [sounddevice](https://python-sounddevice.readthedocs.io) (PortAudio) · [pynput](https://pynput.readthedocs.io) · [pystray](https://github.com/moses-palmer/pystray) · [pyperclip](https://pyperclip.readthedocs.io) · [pycaw](https://github.com/AndreMiras/pycaw) · [groq](https://github.com/groq/groq-python) · [google-genai](https://github.com/googleapis/python-genai)

## Limitations

- Windows only (uses `winsound`, `winotify`, `pycaw`)
- Cloud transcription only — no offline Whisper mode
- No real-time streaming, no overlay UI, single hotkey, single polish prompt
- Bluetooth HFP profile management is Windows-controlled
