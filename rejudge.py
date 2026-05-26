"""Re-judge cached bench results using structured JSON output (response_schema).

Loads bench_results.json (produced by bench_polish.py), runs the judge again
with forced JSON output so thinking-heavy Pro models can't truncate the reply.
"""
import json
import os
import random
from dotenv import load_dotenv
load_dotenv()

from google import genai
from google.genai import types

JUDGE_MODEL = "gemini-3.1-pro-preview"
SEED = 42

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "winner": {"type": "string", "enum": ["A", "B", "tie"]},
        "reason": {"type": "string"},
    },
    "required": ["winner", "reason"],
}

PROMPT_TEMPLATE = """You are evaluating two cleaned-up dictation transcripts.

ORIGINAL TRANSCRIPT (raw speech-to-text): {original}
LANGUAGE: {lang}

OUTPUT A: {a}
OUTPUT B: {b}

The cleanup task: remove fillers, fix grammar, rewrite for clarity if muddled, preserve meaning exactly, never add information, keep the same language.

Pick the better output. If genuinely indistinguishable, return "tie"."""


def main():
    with open("bench_results.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    candidates = data["candidates"]
    results = data["results"]
    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    random.seed(SEED)

    wins = {m: 0 for m in candidates}
    ties = 0
    errors = 0

    for i, r in enumerate(results):
        case = r["case"]
        a_model, b_model = candidates[:]
        random.shuffle([a_model, b_model])  # use a fresh shuffle per case
        shuffled = list(candidates)
        random.shuffle(shuffled)
        a_model, b_model = shuffled
        a_out = r["models"][a_model]["output"]
        b_out = r["models"][b_model]["output"]
        if not (a_out and b_out):
            print(f"[{i+1:2}] {case['name']}: SKIP (empty output)")
            errors += 1
            continue
        prompt = PROMPT_TEMPLATE.format(original=case["text"], lang=case["lang"], a=a_out, b=b_out)
        try:
            resp = client.models.generate_content(
                model=JUDGE_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.0,
                    max_output_tokens=4096,
                    response_mime_type="application/json",
                    response_schema=JUDGE_SCHEMA,
                ),
            )
            text = (resp.text or "").strip()
            j = json.loads(text)
            label = j["winner"]
            winner = a_model if label == "A" else (b_model if label == "B" else "tie")
            reason = j["reason"][:150]
            if winner == "tie":
                ties += 1
            else:
                wins[winner] += 1
            r["judgment"] = {
                "a_model": a_model, "b_model": b_model,
                "label_winner": label, "model_winner": winner, "reason": reason,
            }
            print(f"[{i+1:2}] {case['name']:25s}  winner: {winner:25s}  ({reason[:80]})")
        except Exception as e:
            errors += 1
            r["judgment"] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
            print(f"[{i+1:2}] {case['name']:25s}  ERROR: {type(e).__name__}: {str(e)[:80]}")

    print("\n" + "=" * 60)
    print(f"Judge ({JUDGE_MODEL}):")
    for m in candidates:
        print(f"  {m:30s}: {wins[m]}")
    print(f"  {'tie':30s}: {ties}")
    print(f"  {'errors/skipped':30s}: {errors}")

    with open("bench_results.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("\nUpdated bench_results.json")


if __name__ == "__main__":
    main()
