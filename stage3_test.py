"""Stage 3 test: feed sample transcripts (muddled EN, clean EN, RU) through Gemini polish."""
import sys
from dotenv import load_dotenv
load_dotenv()

from llm import polish

CASES = [
    {
        "name": "muddled English",
        "lang": "English",
        "input": "so um like I was thinking that you know maybe we should uh kind of like go to the the store later today because we like ran out of milk and um also bread I think",
        "must_contain_any": ["store", "milk", "bread"],
        "must_not_contain": ["um", "uh", "like ", "you know"],
        "must_be_lang": "en",  # heuristic
    },
    {
        "name": "clean English (should stay close)",
        "lang": "English",
        "input": "The quarterly report is due on Friday. Please review it before submitting.",
        "must_contain_any": ["quarterly report", "Friday"],
        "must_not_contain": [],
        "must_be_lang": "en",
    },
    {
        "name": "Russian",
        "lang": "Russian",
        "input": "ну короче я думаю что нам типа надо завтра пойти в магазин потому что эм закончилось молоко и хлеб тоже короче",
        "must_contain_any": ["магазин", "молоко", "хлеб"],
        "must_not_contain": ["короче", "типа", "эм"],
        "must_be_lang": "ru",
    },
    {
        "name": "empty input",
        "lang": "",
        "input": "",
        "must_contain_any": [],
        "must_not_contain": [],
        "must_be_lang": None,
        "expect_empty": True,
    },
]


def detect_script(s: str) -> str:
    cyr = sum(1 for c in s if "Ѐ" <= c <= "ӿ")
    lat = sum(1 for c in s if c.isascii() and c.isalpha())
    if cyr > lat:
        return "ru"
    if lat > 0:
        return "en"
    return ""


def main():
    all_pass = True
    for case in CASES:
        print(f"\n--- {case['name']} ---")
        print(f"  IN:  {case['input']!r}")
        out = polish(case["input"], case["lang"])
        print(f"  OUT: {out!r}")

        ok = True
        if case.get("expect_empty"):
            if out != "":
                print(f"  FAIL: expected empty output, got {out!r}")
                ok = False
        else:
            for sub in case["must_contain_any"]:
                if sub.lower() not in out.lower():
                    print(f"  FAIL: missing expected substring {sub!r}")
                    ok = False
            for sub in case["must_not_contain"]:
                if sub.lower() in out.lower():
                    print(f"  FAIL: should not contain {sub!r}")
                    ok = False
            if case["must_be_lang"]:
                detected = detect_script(out)
                if detected != case["must_be_lang"]:
                    print(f"  FAIL: expected language {case['must_be_lang']!r}, got {detected!r}")
                    ok = False
        if ok:
            print("  PASS")
        all_pass &= ok

    if all_pass:
        print("\nStage 3 PASS.")
        sys.exit(0)
    print("\nStage 3 FAIL.")
    sys.exit(1)


if __name__ == "__main__":
    main()
