"""Stage 4 test: clipboard write + restore lifecycle.

Verifies:
1. The polished text is on the clipboard during the paste window.
2. The previous clipboard is restored after `restore_delay`.
3. Unicode (Cyrillic) round-trips correctly.
"""
import sys
import time
import threading
import pyperclip

from paste import paste_text


def run_case(name: str, initial: str, new: str) -> bool:
    print(f"\n--- {name} ---")
    pyperclip.copy(initial)
    got_initial = pyperclip.paste()
    if got_initial != initial:
        print(f"  FAIL: could not set initial clipboard ({got_initial!r} != {initial!r})")
        return False
    print(f"  initial clipboard: {initial!r}")

    # Run paste in background with send_keys=False so we don't pollute the focused window.
    # Use a longer restore_delay so we can observe the mid-flight state.
    t = threading.Thread(
        target=paste_text,
        args=(new,),
        kwargs={"restore_delay": 0.6, "send_keys": False},
    )
    t.start()

    time.sleep(0.15)  # mid-flight check
    mid = pyperclip.paste()
    print(f"  mid-flight clipboard: {mid!r}")
    mid_ok = (mid == new)

    t.join()
    final = pyperclip.paste()
    print(f"  final clipboard:      {final!r}")
    final_ok = (final == initial)

    print(f"  mid-flight has new text: {mid_ok}")
    print(f"  final restored to initial: {final_ok}")
    return mid_ok and final_ok


def main():
    cases = [
        ("ascii", "ORIGINAL_TEXT", "Hello, world!"),
        ("unicode (Cyrillic)", "previous note", "Привет, как дела? Это тест."),
        ("empty initial", "", "Some pasted content."),
    ]
    all_pass = all(run_case(*c) for c in cases)

    # Also verify the key-send path doesn't throw (we don't observe the receiver)
    print("\n--- send_keys=True smoke test ---")
    pyperclip.copy("sentinel")
    try:
        paste_text("smoke", restore_delay=0.2, send_keys=True)
        time.sleep(0.3)
        after = pyperclip.paste()
        # Key send target was whatever window was focused — likely the terminal.
        # We only care that the function didn't raise and the clipboard was restored.
        print(f"  no exception; final clipboard: {after!r}")
        smoke_ok = (after == "sentinel")
        print(f"  clipboard restored after send_keys=True: {smoke_ok}")
        all_pass &= smoke_ok
    except Exception as e:
        print(f"  FAIL: {type(e).__name__}: {e}")
        all_pass = False

    if all_pass:
        print("\nStage 4 PASS.")
        sys.exit(0)
    print("\nStage 4 FAIL.")
    sys.exit(1)


if __name__ == "__main__":
    main()
