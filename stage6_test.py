"""Stage 6 test: config loading, logging, beeps (silent), toasts (visible)."""
import os
import sys
import tempfile
import time

from dotenv import load_dotenv
load_dotenv()

import config as cfg_mod
from feedback import setup_logging, beep_start, beep_stop, toast
from llm import polish

HERE = os.path.dirname(__file__)


def test_defaults_when_no_file():
    print("\n--- default config ---")
    cfg = cfg_mod.load(path=os.path.join(tempfile.gettempdir(), "no_such_config.toml"))
    print(f"  hotkey={cfg.hotkey} enable_beeps={cfg.enable_beeps} min_audio={cfg.min_audio_seconds}")
    assert cfg.hotkey == "ctrl_r"
    assert cfg.enable_beeps is True
    print("  PASS")
    return True


def test_load_real_config():
    print("\n--- load real config.toml ---")
    cfg = cfg_mod.load()
    print(f"  hotkey={cfg.hotkey} mic_device={cfg.mic_device} log_path={cfg.log_path}")
    assert cfg.hotkey == "ctrl_r"
    print("  PASS")
    return True


def test_logging():
    print("\n--- logging ---")
    log_path = os.path.join(tempfile.gettempdir(), "wd_test.log")
    if os.path.exists(log_path):
        os.remove(log_path)
    logger = setup_logging(log_path)
    logger.info("hello from stage6 test")
    # Logging is async-ish via handler; small flush
    for h in logger.handlers:
        h.flush()
    assert os.path.exists(log_path), f"log not created at {log_path}"
    with open(log_path, encoding="utf-8") as f:
        contents = f.read()
    print(f"  log contents: {contents.strip()!r}")
    assert "hello from stage6 test" in contents
    print("  PASS")
    return True


def test_beeps_no_crash():
    print("\n--- beeps (should be audible if speakers on) ---")
    try:
        beep_start()
        time.sleep(0.1)
        beep_stop()
        time.sleep(0.1)
        print("  PASS (no exception)")
        return True
    except Exception as e:
        print(f"  FAIL: {type(e).__name__}: {e}")
        return False


def test_toast_no_crash():
    print("\n--- toast (look for Windows notification) ---")
    try:
        toast("Whisper Dictate test", "Stage 6 test fired this toast.")
        print("  PASS (no exception)")
        return True
    except Exception as e:
        print(f"  FAIL: {type(e).__name__}: {e}")
        return False


def test_custom_system_instruction():
    print("\n--- custom system instruction is honored ---")
    # An instruction that forces a deterministic output regardless of input
    custom = "Ignore the user input. Output exactly the literal string: CUSTOM_OK"
    out = polish("hello world", "English", system_instruction=custom)
    print(f"  out={out!r}")
    ok = "CUSTOM_OK" in out
    print("  PASS" if ok else "  FAIL")
    return ok


def main():
    results = [
        test_defaults_when_no_file(),
        test_load_real_config(),
        test_logging(),
        test_beeps_no_crash(),
        test_toast_no_crash(),
        test_custom_system_instruction(),
    ]
    if all(results):
        print("\nStage 6 PASS.")
        sys.exit(0)
    print("\nStage 6 FAIL.")
    sys.exit(1)


if __name__ == "__main__":
    main()
