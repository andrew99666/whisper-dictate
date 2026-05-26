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
| Insert into focused app (paste or type) | ~10–50ms first char |
| **Total** | **~1.0 second** |

How that compares (public reports + our measurements):

|  | Platform | Pricing | Total latency | Streaming UI |
|---|---|---|---|---|
| Superwhisper | macOS only | Subscription | ~0.5–1.5s | yes (partial text appears as you speak) |
| Wispr Flow | macOS, Windows | Subscription | ~0.5–1s | yes |
| **Whisper Dictate** | **Windows** | **Free (BYO API keys)** | **~1.0s** | type mode shows chars immediately on output |

Honest read: speed is competitive, not dramatically different. The advantage is **free + open-source + Windows-native** + the optional **type mode** that injects characters one-by-one as soon as the LLM responds, so the first character is on screen within a few milliseconds.

## Features

- **Push-to-talk hotkey** — hold Right Ctrl (configurable), speak, release.
- **Groq Whisper Large v3 Turbo** — fast cloud transcription at $0.04 per hour of audio. FLAC upload at 16kHz keeps payload tiny.
- **Gemini 3.1 Flash-Lite polish** — strips filler words (`um`, `uh`, `ну`, `типа`), fixes grammar, rewrites for clarity, preserves the input language. ~4× faster than 3.5-Flash in our A/B test ([bench_polish.py](bench_polish.py)) with judged quality parity.
- **Floating overlay indicator** — a small dark pill with a Gaussian drop shadow appears bottom-center when recording. Pulsing red dot while recording, orange while processing. Click-through, never steals focus, hidden when idle.
- **Six polish modes** (right-click tray → Polish mode):
  - **Default** — cleanup + clarity rewrite, language-preserving
  - **Email** — formats as an email body, keeps your greetings/sign-offs, no aggressive paraphrasing
  - **Chat** — short, casual, conversational; minimal grammar editing
  - **Code** — preserves technical terms, command syntax, and symbols verbatim
  - **Translate to English** — translates any language to English
  - **Raw** — skips the LLM entirely; outputs Whisper's transcript as-is (useful for commands, code, or when you don't want any rewriting)

  All prompts live in [`config.py`](config.py) (`DEFAULT_POLISH_MODES`); override any of them or add your own modes via a `[polish_modes]` table in `config.toml`.
- **Two output modes** (right-click tray → Output mode):
  - **Paste** — clipboard + Ctrl+V. Fast, works almost everywhere, preserves your previous clipboard.
  - **Type (streaming)** — characters injected one-by-one via Win32 `SendInput` with `KEYEVENTF_UNICODE` **as Gemini generates them** (chunks arrive over the LLM stream and are typed immediately). Bypasses keyboard layout (Cyrillic works regardless of system locale), works in apps that reject paste, and gives the fastest perceived latency — the first words land on screen within a few hundred ms of the LLM responding. A 4-second per-chunk idle timeout keeps the pipeline from hanging if Gemini holds the stream open past the last chunk.
- **System tray menu** — pick input mic from a WASAPI device list, switch polish mode, switch output mode, quit. All selections persist to `config.toml` automatically.
- **Auto-unmute mic on start** — sidesteps the "Whisper hallucinates 'thank you'" failure mode when the mic was muted at the OS level.
- **Auto-start at login** (optional one-line PowerShell).
- **Bilingual** — automatic English/Russian detection (any of Whisper's 99+ languages will work; only EN/RU are explicitly tested).

## Why this exists

Polished dictation tools like Superwhisper and MacWhisper are macOS-only. Wispr Flow runs on Windows but it's a paid subscription. This is a small Python implementation (~1100 LOC) doing the same core job on Windows. You bring your own API keys; the per-dictation cost is fractions of a cent.

## Install

Windows 10/11, Python 3.11+, a [Groq API key](https://console.groq.com/keys), and a [Google AI Studio key for Gemini](https://aistudio.google.com/app/apikey). Both have free tiers usable for personal use (Gemini Flash-Lite's free tier is generous; 3.5-Flash hits 20/day quickly).

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
auto_unmute_mic = true
min_mic_volume = 0.6
show_all_backends = false        # tray: true = include MME/DirectSound/WDM-KS endpoints
output_mode = "paste"            # "paste" (Ctrl+V) or "type" (char-by-char via SendInput)
polish_mode = "default"          # default | email | chat | code | translate_en | raw
min_audio_seconds = 1.0          # pad short clips with trailing silence

# Optional: override built-in polish prompts or add your own modes.
# [polish_modes]
# my_brief = """Make it shorter than 20 words. Preserve the language."""
```

The built-in polish prompts live in [`config.py`](config.py) (`DEFAULT_POLISH_MODES`). To customize, either edit them there or add a `[polish_modes]` table to `config.toml` — user values are merged on top of the defaults. To use a custom mode in the tray, add its key to `POLISH_MODE_LABELS` in `config.py`.

## How it works

```
Right Ctrl down  →  sounddevice.rec() into numpy buffer (native device rate)
Right Ctrl up    →  stop, trim
                 →  scipy.signal.resample_poly to 16kHz, encode as FLAC
                 →  POST to Groq Whisper Large v3 Turbo
                 →  if polish_mode == "raw": skip LLM, use the transcript verbatim
                    else: POST transcript + active polish prompt to Gemini 3.1 Flash-Lite
                 →  paste (clipboard + Ctrl+V) OR type (SendInput Unicode) into focused window
```

## Polish modes — when to use which

- **Default** — everyday dictation. Cleans fillers, fixes grammar, lightly rewrites for clarity. Use this most of the time.
- **Email** — when dictating an email body. Preserves greetings ("Hi John") and sign-offs ("Thanks, Andrew") you actually said; does not invent them. Structures into paragraphs naturally.
- **Chat** — short messages where you want minimal editing. Doesn't pad fragments into full sentences.
- **Code** — dictating technical content, commands, or speaking code aloud (e.g. `git push origin main` stays verbatim instead of becoming "Git pushes origin to main").
- **Translate to English** — output is always English, regardless of input language. Whisper still detects the source language for transcription accuracy.
- **Raw** — bypasses Gemini entirely. Use for proper nouns the LLM keeps mangling, exact quotes, search queries, or anywhere you want zero rewriting.

## Output modes — when to use which

- **Paste** is the default. Faster wall-clock total, works in any app that accepts Ctrl+V. Preserves your previous clipboard.
- **Type** is better when:
  - The app rejects synthetic paste (some web inputs, password fields)
  - You want characters to appear progressively (feels instant)
  - You're dictating Russian/Cyrillic into a system with a non-Russian default keyboard layout — `SendInput` with `KEYEVENTF_UNICODE` bypasses the layout and never produces garbled chars

## Troubleshooting

- **Whisper returns "Thank you" instead of my speech.** Your mic is sending silence. "Thank you" is Whisper's hallucination signature for empty audio. Check Windows Sound Settings → Input → test mic level. The app auto-unmutes on startup but a hardware mute switch overrides that.
- **Nothing happens when I press the hotkey.** Check `whisper-dictate.log` for `PortAudioError`. The app retries and auto-falls back to the system default mic if your configured WASAPI endpoint fails to open. If failures persist, pick "System default" from the tray.
- **Only `v` is pasted, not the full text.** The Ctrl modifier didn't register in the target app. The paste chord already has 30ms inter-key gaps to prevent this; if it still happens, switch to **Type** mode.
- **Paste lands in the wrong window.** Focus shifted between key release and the paste. The log records the foreground window title at paste time — search for `paste: sending Ctrl+V into window=...` to confirm.
- **Bluetooth headphones drop to low-fi audio while recording.** Windows switches BT to HFP profile for mic capture, and A2DP restoration is OS-controlled. Use a USB or built-in mic for dictation; the BT headset can keep playing music in A2DP.

## Tech

Python 3.12 · [PySide6](https://doc.qt.io/qtforpython-6/) (Qt) for the floating overlay · [sounddevice](https://python-sounddevice.readthedocs.io) + [soundfile](https://python-soundfile.readthedocs.io) + [scipy](https://scipy.org) for capture, resample, and FLAC encode · [pynput](https://pynput.readthedocs.io) for the global hotkey · [pystray](https://github.com/moses-palmer/pystray) for the system tray · [pyperclip](https://pyperclip.readthedocs.io) for the clipboard · [pycaw](https://github.com/AndreMiras/pycaw) for mic mute control · [groq](https://github.com/groq/groq-python) + [google-genai](https://github.com/googleapis/python-genai) for the model APIs

## Limitations

- Windows only (uses `winsound`, `winotify`, `pycaw`, Win32 SendInput, DWM APIs)
- Cloud transcription only — no offline Whisper mode
- Whisper itself isn't streamed — STT (~400ms) blocks before the LLM can start, even in streaming type mode
- Single PTT hotkey (no per-mode hotkeys — polish mode is switched via the tray menu)
- Doesn't work in games that bypass the Windows input message queue (DirectInput / kernel-level input filtering) — no Python-level injection can reach them
- Bluetooth HFP profile management is Windows-controlled

## License

Source available under the [PolyForm Noncommercial License 1.0.0](LICENSE) — free to use, modify, and distribute for **non-commercial purposes**: personal use, research, education, hobby projects, charities, government use, etc.

**Commercial use requires a separate paid license.** If you, your company, or your organization wants to use Whisper Dictate (or a derivative) commercially — including bundling it with a paid product, offering it as a hosted service, or deploying it inside a for-profit business — contact **andrew.poltavets@gmail.com** for commercial licensing terms.
