"""Stage 5 smoke test: import everything, build the Tray, run for ~2s, then quit cleanly.

This doesn't test the full PTT flow (that requires you to hold a key + speak),
but it confirms the app boots, the tray icon initializes, state transitions work,
and shutdown is clean. Interactive verification happens by running `main.py`.
"""
import sys
import time
import threading

from dotenv import load_dotenv
load_dotenv()

# Import everything main.py imports — surfaces any import-time bugs.
from audio import Recorder, SAMPLE_RATE, pad_to_min_duration  # noqa: F401
from stt import transcribe  # noqa: F401
from llm import polish  # noqa: F401
from paste import paste_text  # noqa: F401
from tray import Tray


def main():
    print("All modules imported OK.")

    stopped = threading.Event()

    def on_quit():
        print("on_quit fired")
        stopped.set()

    tray = Tray(on_quit=on_quit)

    def cycle_states_then_quit():
        # Wait briefly for the tray loop to spin up
        time.sleep(0.8)
        for state in ("recording", "processing", "idle"):
            print(f"  set_state({state!r})")
            tray.set_state(state)
            time.sleep(0.4)
        print("  calling tray.stop()")
        tray.stop()

    t = threading.Thread(target=cycle_states_then_quit, daemon=True)
    t.start()

    try:
        tray.run()  # blocks
    except Exception as e:
        print(f"FAIL: tray.run raised {type(e).__name__}: {e}")
        return 1

    t.join(timeout=5)
    print("Stage 5 smoke test PASS.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
