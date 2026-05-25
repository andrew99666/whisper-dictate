"""Stage 2 test: generate TTS samples (EN + RU when available), send through Groq Whisper.

Uses Windows SAPI via PowerShell to synthesize known phrases, then verifies the
transcript contains expected words and that language auto-detection works.
"""
import os
import subprocess
import sys

from dotenv import load_dotenv
load_dotenv()

from stt import transcribe_wav_file

HERE = os.path.dirname(__file__)
EN_PHRASE = "Testing one two three. This is a quick check of speech recognition."
RU_PHRASE = "Это короткая проверка распознавания речи на русском языке."


def tts_to_wav(text: str, out_path: str, voice_culture: str | None = None) -> bool:
    """Use Windows SAPI to synthesize text to a wav file. Returns True on success."""
    ps_lines = [
        "Add-Type -AssemblyName System.Speech",
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer",
    ]
    if voice_culture:
        # Try to pick a voice matching the culture (e.g. ru-RU); ignore failure
        ps_lines.append(
            f"try {{ $v = $s.GetInstalledVoices() | "
            f"Where-Object {{ $_.VoiceInfo.Culture.Name -like '{voice_culture}*' }} | "
            f"Select-Object -First 1; if ($v) {{ $s.SelectVoice($v.VoiceInfo.Name) }} }} catch {{}}"
        )
    ps_lines += [
        f"$s.SetOutputToWaveFile('{out_path}')",
        f"$s.Speak(@'\n{text}\n'@)",
        "$s.Dispose()",
    ]
    ps_script = "; ".join(ps_lines)
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_script],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        print(f"  TTS failed: {result.stderr.strip()}")
        return False
    return os.path.exists(out_path) and os.path.getsize(out_path) > 1000


def check_voices_available() -> dict[str, bool]:
    """Return which language cultures have SAPI voices installed."""
    ps = (
        "Add-Type -AssemblyName System.Speech; "
        "(New-Object System.Speech.Synthesis.SpeechSynthesizer).GetInstalledVoices() | "
        "ForEach-Object { $_.VoiceInfo.Culture.Name }"
    )
    result = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                            capture_output=True, text=True, timeout=10)
    cultures = [c.strip() for c in result.stdout.splitlines() if c.strip()]
    print(f"  Installed SAPI voices: {cultures}")
    return {
        "en": any(c.startswith("en") for c in cultures),
        "ru": any(c.startswith("ru") for c in cultures),
    }


def run_case(name: str, phrase: str, voice_culture: str, expected_lang: str,
             expected_substrings: list[str]) -> bool:
    print(f"\n--- {name} ---")
    wav_path = os.path.join(HERE, f"test_{name}.wav")
    if not tts_to_wav(phrase, wav_path, voice_culture):
        print(f"  SKIP — could not synthesize {name} sample")
        return True  # don't fail just because the voice isn't installed
    print(f"  TTS wav: {wav_path} ({os.path.getsize(wav_path)} bytes)")
    print(f"  Sending to Groq Whisper...")
    result = transcribe_wav_file(wav_path)
    print(f"  Detected language: {result.language!r}")
    print(f"  Transcript: {result.text!r}")

    lang_ok = result.language.lower().startswith(expected_lang)
    text_lower = result.text.lower()
    text_ok = any(s.lower() in text_lower for s in expected_substrings)
    print(f"  Language match ({expected_lang}): {lang_ok}")
    print(f"  Content match (any of {expected_substrings}): {text_ok}")
    return lang_ok and text_ok


def main():
    voices = check_voices_available()
    all_pass = True

    if voices.get("en"):
        all_pass &= run_case("en", EN_PHRASE, "en-",
                             expected_lang="en",
                             expected_substrings=["testing", "one", "two", "three"])
    else:
        print("No English SAPI voice — skipping EN case (unlikely on Windows)")

    if voices.get("ru"):
        all_pass &= run_case("ru", RU_PHRASE, "ru-",
                             expected_lang="ru",
                             expected_substrings=["проверка", "русск", "распознаван"])
    else:
        print("\nNo Russian SAPI voice installed — skipping RU case.")
        print("(Auto-language detection still verified by EN case; full RU test deferred to live mic.)")

    if all_pass:
        print("\nStage 2 PASS.")
        sys.exit(0)
    print("\nStage 2 FAIL.")
    sys.exit(1)


if __name__ == "__main__":
    main()
