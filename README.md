# Whisper Dictate — Push-to-Talk Voice Dictation for Windows

Free, open-source voice dictation for Windows. Hold a hotkey, speak, release — get clean text inserted into the focused app in about **1 second**, end-to-end. A [Superwhisper](https://superwhisper.com) / [Wispr Flow](https://wisprflow.ai) alternative that runs on Windows, uses [Groq Whisper Large v3 Turbo](https://console.groq.com/docs/model/whisper-large-v3-turbo) for transcription, and [Gemini 3.1 Flash-Lite](https://ai.google.dev) for cleanup.

Auto-detects **English and Russian** per utterance (Whisper supports 99+ languages).

## Speed

End-to-end pipeline from key release to inserted text, measured on a typical residential connection:

| Stage | Time |
|---|---|
| Audio resample 48kHz → 16kHz + FLAC encode | ~10ms |
| Groq Whisper Large v3 Turbo (over network) | ~400ms |
| Gemini 3.1 Flash-Lite polish | ~600ms |
| Clipboard write + Ctrl+V into focused app | ~10ms |
| **Total** | **~1.0 second** |

How that compares (public reports + our measurements):

|  | Platform | Pricing | Total latency |
|---|---|---|---|
| Superwhisper | macOS only | Subscription | ~0.5–1.5s |
| Wispr Flow | macOS, Windows | Subscription | ~0.5–1s |
| **Whisper Dictate** | **Windows** | **Free (BYO API keys)** | **~1.0s** |

Honest read: speed is competitive, not dramatically different. The advantage is **free + open-source + Windows-native**.

## Features

- **Push-to-talk hotkey** — hold Right Ctrl (configurable), speak, release.
- **Groq Whisper Large v3 Turbo** — fast cloud transcription at $0.04 per hour of audio. FLAC upload at 16kHz keeps payload tiny.
- **Gemini 3.1 Flash-Lite polish** — strips filler words (`um`, `uh`, `ну`, `типа`), fixes grammar, rewrites for clarity, preserves the input language. Sub-second response for typical dictation lengths.
- **Tone-aware cleanup** — the default, email, chat, and translate modes use a compact personal tone guide: direct, practical, lightly warm, and plain-spoken without preserving typos or rough grammar.
- **Prompt-safe polishing** — dictated text is treated as inert transcript data, not a command for Gemini to execute. If you dictate "write me a letter...", the app cleans that request instead of generating the letter.
- **Floating overlay indicator** — a small dark pill with a Gaussian drop shadow appears bottom-center when recording. Pulsing red dot while recording, orange while processing. Click-through, never steals focus, hidden when idle.
- **Six polish modes** (right-click tray → Polish mode):
  - **Default** — cleanup + clarity rewrite, language-preserving
  - **Email** — formats as an email body, keeps your greetings/sign-offs, no aggressive paraphrasing
  - **Chat** — short, casual, conversational; minimal grammar editing
  - **Code** — preserves technical terms, command syntax, and symbols verbatim
  - **Translate to English** — translates any language to English
  - **Raw** — skips the LLM entirely; outputs Whisper's transcript as-is (useful for commands, code, or when you don't want any rewriting)

  All prompts live in [`config.py`](config.py) (`DEFAULT_POLISH_MODES`); override any of them or add your own modes via a `[polish_modes]` table in `config.toml`.
- **Clipboard paste output** — clipboard write + `Ctrl+V` into the focused window. Works anywhere paste does (Notepad, Office, IDEs, browsers, Slack, Discord). By default, the dictated text stays on the clipboard after paste so a missed auto-paste is recoverable with a manual `Ctrl+V`. Unicode-safe: Russian text round-trips cleanly through the Windows clipboard regardless of system locale.
- **System tray menu** — pick input mic from a WASAPI device list, switch polish mode, quit. All selections persist to `config.toml` automatically.
- **Pre-flight mic mute check + auto-unmute** — every PTT press first checks whether the default mic is muted (~0.2ms call into a thread-isolated `pycaw` worker). If muted, it unmutes; if it *can't* be unmuted (hardware mute switch / no permission), the overlay shows a solid red **"Mic muted"** pill instead of "Recording" and the recording is skipped entirely. No more silently dictating into a muted mic and getting Whisper's "Thank you" hallucination pasted into your window.
- **Silent-mic guard** (final safety net) — if recording somehow still captures essentially silence (peak < 0.005), the pipeline short-circuits before the API call and toasts a warning instead of pasting hallucinated text.
- **Auto-start at login** (optional one-line PowerShell).
- **Bilingual** — automatic English/Russian detection (any of Whisper's 99+ languages will work; only EN/RU are explicitly tested).

## Why this exists

Polished dictation tools like Superwhisper and MacWhisper are macOS-only. Wispr Flow runs on Windows but it's a paid subscription. This is a small Python implementation (~1100 LOC) doing the same core job on Windows. You bring your own API keys; the per-dictation cost is fractions of a cent.

## Install

Windows 10/11, Python 3.11+, a [Groq API key](https://console.groq.com/keys), and a [Google AI Studio key for Gemini](https://aistudio.google.com/app/apikey). Both have free tiers usable for personal use.

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

A gray circle icon appears in your system tray. Hold **Right Ctrl**, speak, release — text appears in whatever window has focus.

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
hotkey = "ctrl_r"                # any pynput Key name: ctrl_r, ctrl_l, f9, menu, ...
# mic_device = 1                 # tray menu also sets this; leave blank for system default
show_all_backends = false        # tray: true = include MME/DirectSound/WDM-KS endpoints
polish_mode = "default"          # default | email | chat | code | translate_en | raw
min_audio_seconds = 1.0          # pad short clips with trailing silence
disable_gemini_thinking = false  # true is faster; false is safer for polish quality
restore_clipboard = false        # true restores the previous clipboard after paste
clipboard_restore_delay = 1.0    # seconds to wait before restore_clipboard runs

# Optional: override built-in polish prompts or add your own modes.
# [polish_modes]
# my_brief = """Make it shorter than 20 words. Preserve the language."""
```

The built-in polish prompts live in [`config.py`](config.py) (`DEFAULT_POLISH_MODES`). To customize, either edit them there or add a `[polish_modes]` table to `config.toml` — user values are merged on top of the defaults. To use a custom mode in the tray, add its key to `POLISH_MODE_LABELS` in `config.py`.

`disable_gemini_thinking = false` keeps polish quality conservative. Set it to `true` only if you want to trade some prompt-following reliability for lower Gemini latency.

`restore_clipboard = false` is intentional. If the target app misses the synthetic `Ctrl+V`, the dictated text remains the current clipboard item and you can paste it manually. If you set it to `true`, Windows clipboard history may show the previous clipboard item as newest because the app restores it after paste.

## How it works

```
Right Ctrl down  →  re-unmute default mic (in case Windows muted it after sleep)
                 →  sounddevice.InputStream callback → chunks list (grows as you speak,
                    no pre-allocated buffer, no recording length cap)
Right Ctrl up    →  stop stream, drain callbacks, concatenate chunks
                 →  scipy.signal.resample_poly to 16kHz, encode as FLAC
                 →  POST to Groq Whisper Large v3 Turbo
                 →  if polish_mode == "raw": skip LLM, use the transcript verbatim
                    else: POST transcript + active polish prompt to Gemini 3.1 Flash-Lite
                 →  copy polished text to clipboard, send Ctrl+V
```

Mic safety is two-layered:
1. **Pre-flight check** on every PTT press: `mic_control` (a dedicated daemon
   thread that owns pycaw COM objects forever, so they're never GC'd across
   threads — that race used to crash the app) reports mute state in ~0.2ms.
   If muted, we try to unmute. If unmute fails or the mic is still muted
   (hardware switch), the overlay flips to **"Mic muted"** and recording is
   skipped.
2. **Post-record fallback**: if the buffer is still essentially silent
   (peak < 0.005) after recording, the pipeline short-circuits and toasts —
   catches edge cases like a wrong default device.

## Polish modes — when to use which

- **Default** — everyday dictation. Cleans fillers, fixes grammar, lightly rewrites for clarity, and keeps the configured personal tone. Use this most of the time.
- **Email** — when dictating an email body. Preserves greetings ("Hi John") and sign-offs ("Thanks, Andrew") you actually said; does not invent them. Structures into paragraphs naturally.
- **Chat** — short messages where you want minimal editing. Doesn't pad fragments into full sentences.
- **Code** — dictating technical content, commands, or speaking code aloud (e.g. `git push origin main` stays verbatim instead of becoming "Git pushes origin to main").
- **Translate to English** — output is always English, regardless of input language. Whisper still detects the source language for transcription accuracy.
- **Raw** — bypasses Gemini entirely. Use for proper nouns the LLM keeps mangling, exact quotes, search queries, or anywhere you want zero rewriting.

## Troubleshooting

- **Overlay shows "Mic muted" when I press the hotkey.** The pre-flight check detected the default mic is muted at the OS level AND auto-unmute couldn't fix it (usually a hardware mute switch on the mic itself, or a different mic being the default than the one you're trying to use). Check the physical mute switch, or pick the right mic from the tray's Input device menu.
- **Toast says "Mic captured silence".** Audio was captured but came out silent (different from "Mic muted" — this is post-record). Often means the wrong device is the default, or the device opened but isn't getting signal. Check Windows Sound Settings → Input.
- **Nothing happens when I press the hotkey.** Check `whisper-dictate.log` for `PortAudioError`. The recorder retries and auto-falls back to the system default mic if your configured WASAPI endpoint fails to open. If failures persist, pick "System default" from the tray.
- **Paste lands in the wrong window.** Focus shifted between key release and the paste. The log records the foreground window title at paste time — search for `paste: sending Ctrl+V into window=...` to confirm.
- **Paste doesn't work at all in app X.** Some games and a few specialty apps (DRM'd web inputs, password fields, kernel-level anti-cheat) reject synthetic paste. There's no workaround at the Python level — that input layer is below us.
- **Bluetooth headphones drop to low-fi audio while recording.** Windows switches BT to HFP profile for mic capture, and A2DP restoration is OS-controlled. Use a USB or built-in mic for dictation; the BT headset can keep playing music in A2DP.

## Tech

Python 3.12 · [PySide6](https://doc.qt.io/qtforpython-6/) (Qt) for the floating overlay · [sounddevice](https://python-sounddevice.readthedocs.io) + [soundfile](https://python-soundfile.readthedocs.io) + [scipy](https://scipy.org) for capture, resample, and FLAC encode · [pynput](https://pynput.readthedocs.io) for the global hotkey · [pystray](https://github.com/moses-palmer/pystray) for the system tray · [pyperclip](https://pyperclip.readthedocs.io) for the clipboard · [pycaw](https://github.com/AndreMiras/pycaw) (in an isolated daemon thread) for mic mute control · [groq](https://github.com/groq/groq-python) + [google-genai](https://github.com/googleapis/python-genai) for the model APIs

## Limitations

- Windows only (uses `winotify`, DWM APIs, Win32 via `ctypes`)
- Cloud transcription only — no offline Whisper mode
- Single PTT hotkey (no per-mode hotkeys — polish mode is switched via the tray menu)
- Paste mode only — apps that reject `Ctrl+V` paste won't accept input from this tool (typing-mode alternatives were too unreliable across Windows / Notepad / Chrome and were removed)
- Bluetooth HFP profile management is Windows-controlled

## Crash diagnostics

`pythonw.exe` silently discards `stderr`, so unhandled errors normally vanish. The app installs three safety nets so crashes leave a trace next to the project root:

- **`whisper-dictate.log`** — all normal logging + `sys.excepthook` and `threading.excepthook` write any unhandled Python exception (with full stack) here.
- **`stderr.log`** — `sys.stderr` is redirected to this file so anything that bypasses the logger (e.g. comtypes `Exception ignored in __del__` messages) lands somewhere readable.
- **`fault.log`** — `faulthandler.enable()` writes native C-level stack traces here on segfaults / access violations (PortAudio, Qt, ctypes). If the process dies hard, this is where the cause shows up.

## License

Source available under the [PolyForm Noncommercial License 1.0.0](LICENSE) — free to use, modify, and distribute for **non-commercial purposes**: personal use, research, education, hobby projects, charities, government use, etc.

**Commercial use requires a separate paid license.** If you, your company, or your organization wants to use Whisper Dictate (or a derivative) commercially — including bundling it with a paid product, offering it as a hosted service, or deploying it inside a for-profit business — contact **andrew.poltavets@gmail.com** for commercial licensing terms.
