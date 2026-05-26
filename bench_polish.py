"""A/B benchmark for the LLM polish step.

Compares gemini-3.5-flash vs gemini-3.1-flash-lite on:
  - speed (median + p95 latency over N_RUNS per case)
  - rule-based quality (filler removal, language preservation, length sanity)
  - blind judge ranking (gemini-3.1-pro-preview picks A/B/tie per case)

Output: console summary + bench_results.json with full per-case data.
"""
from __future__ import annotations

import json
import os
import random
import statistics
import time
from typing import Any

from dotenv import load_dotenv
load_dotenv()

from google import genai
from google.genai import types

from llm import SYSTEM_INSTRUCTION

# --- config ---
CANDIDATES = ["gemini-3.5-flash", "gemini-3.1-flash-lite"]
JUDGE_MODEL_CANDIDATES = ["gemini-3.1-pro-preview", "gemini-3.1-pro", "gemini-3-pro-preview", "gemini-2.5-pro"]
N_RUNS = 2  # per case per model
SEED = 42

# Mix of EN/RU, muddled/clean/short/long. Several pulled from real whisper-dictate.log entries.
TEST_CASES: list[dict[str, str]] = [
    {"name": "en_muddled_fillers", "lang": "English",
     "text": "so um like I was thinking that you know maybe we should uh kind of like go to the the store later today because we like ran out of milk and um also bread I think"},
    {"name": "en_clean_short", "lang": "English",
     "text": "The meeting is at 3pm tomorrow."},
    {"name": "en_clean_tech", "lang": "English",
     "text": "Configure the load balancer to use round-robin distribution across the three backend servers."},
    {"name": "en_self_correct", "lang": "English",
     "text": "send the email to John no wait to Mary about the the project status update for Q4"},
    {"name": "en_question_rambling", "lang": "English",
     "text": "Okay, and can you add a new functionality when I go to tray and right click on that tray icon I want to be able to choose input microphone. So basically there will be a list of possible microphones and I want to choose which one to use for... Yeah, which one to use."},
    {"name": "en_long_clean", "lang": "English",
     "text": "The new feature allows users to select their preferred microphone from a list of available input devices displayed in the system tray menu, and the selection persists across application restarts."},
    {"name": "en_proper_nouns", "lang": "English",
     "text": "Send this to Andrew Poltavets at gmail dot com about the WhisperDictate project"},
    {"name": "en_single_word", "lang": "English",
     "text": "okay"},
    {"name": "ru_muddled_fillers", "lang": "Russian",
     "text": "ну короче я думаю что нам типа надо завтра пойти в магазин потому что эм закончилось молоко и хлеб тоже короче"},
    {"name": "ru_clean_short", "lang": "Russian",
     "text": "Встреча завтра в три часа дня."},
    {"name": "ru_long_muddled", "lang": "Russian",
     "text": "А напиши для нас это объявление, которое мы должны сейчас выставить. И также мы справоздание уже сейчас можем сделать? Вот это справоздание финансовое и справоздание ликвидатора. Так, мы сэм цикруем."},
    {"name": "ru_hesitations", "lang": "Russian",
     "text": "Я хотел бы э я хотел бы попросить тебя помочь мне с этой этой задачей"},
    {"name": "ru_eng_techterms", "lang": "Russian",
     "text": "Закоммить мой код в Git и потом запушь на main бранч"},
    {"name": "mixed_ru_en", "lang": "Russian",
     "text": "Это финальный тест микрофона. This is the final test of microphone."},
    {"name": "ru_user_real", "lang": "Russian",
     "text": "А ты вот на этом сайте советовал разместить объявление, но здесь дает максимум 31 день, чтобы оно высвечивалось."},
]


def ping(client: genai.Client, model_id: str) -> bool:
    """Trust no-exception = available. Thinking models can return empty text with low max tokens."""
    try:
        client.models.generate_content(
            model=model_id,
            contents="reply OK",
            config=types.GenerateContentConfig(temperature=0.0, max_output_tokens=200),
        )
        return True
    except Exception as e:
        print(f"  {model_id}: FAIL — {type(e).__name__}: {str(e)[:140]}")
        return False


def polish_once(client: genai.Client, model: str, text: str, lang: str) -> tuple[str, float]:
    user_msg = f"[Detected language: {lang}]\n\n{text}" if lang else text
    t0 = time.monotonic()
    resp = client.models.generate_content(
        model=model,
        contents=user_msg,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            temperature=0.2,
            max_output_tokens=2048,
        ),
    )
    return (resp.text or "").strip(), time.monotonic() - t0


def check_rules(original: str, output: str, lang: str) -> dict[str, bool]:
    out_lower = output.lower()
    is_ru = lang.lower().startswith("ru")
    fillers = (["короче", "типа", " ну,", "эм "] if is_ru
               else [" um ", " uh ", "like, ", "you know,"])
    cyr = sum(1 for c in output if "Ѐ" <= c <= "ӿ")
    lat = sum(1 for c in output if c.isascii() and c.isalpha())
    detected_script = "ru" if cyr > lat else ("en" if lat > 0 else "")
    expected_script = "ru" if is_ru else "en"
    return {
        "no_fillers": not any(f in out_lower for f in fillers),
        "language_preserved": detected_script == expected_script,
        "length_reasonable": 0 < len(output) <= max(len(original) * 2, 80),
        "not_empty": bool(output.strip()),
    }


def judge_pair(client: genai.Client, judge_model: str, original: str, lang: str,
               output_a: str, output_b: str) -> dict[str, Any]:
    prompt = f"""You are evaluating two cleaned-up dictation transcripts.

ORIGINAL TRANSCRIPT (raw speech-to-text): {original}
LANGUAGE: {lang}

OUTPUT A: {output_a}
OUTPUT B: {output_b}

The cleanup task: remove fillers, fix grammar, rewrite for clarity if muddled, preserve meaning exactly, never add information, keep the same language.

Pick the better output. Respond with EXACTLY one JSON object:
{{"winner": "A" or "B" or "tie", "reason": "one short sentence"}}"""
    resp = client.models.generate_content(
        model=judge_model,
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.0, max_output_tokens=200),
    )
    text = (resp.text or "").strip()
    if text.startswith("```"):
        text = text.strip("`").lstrip("json").strip()
    try:
        return json.loads(text)
    except Exception:
        return {"winner": "?", "reason": text[:100]}


def main():
    random.seed(SEED)
    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])

    print("=== verifying candidate models ===")
    for m in CANDIDATES:
        ok = ping(client, m)
        print(f"  {m}: {'OK' if ok else 'FAIL'}")
        if not ok:
            print("  Aborting — candidate model not available.")
            return

    print("\n=== finding judge model ===")
    judge_model = None
    for m in JUDGE_MODEL_CANDIDATES:
        if ping(client, m):
            judge_model = m
            print(f"  using judge: {m}")
            break
    if judge_model is None:
        print("  No judge model available — will skip judging.")

    results: list[dict[str, Any]] = []
    for i, case in enumerate(TEST_CASES):
        print(f"\n[{i+1:2}/{len(TEST_CASES)}] {case['name']} ({case['lang']})")
        print(f"  IN:  {case['text'][:100]}{'...' if len(case['text']) > 100 else ''}")
        case_result: dict[str, Any] = {"case": case, "models": {}}

        for model in CANDIDATES:
            outs, lats = [], []
            for _ in range(N_RUNS):
                try:
                    o, l = polish_once(client, model, case["text"], case["lang"])
                except Exception as e:
                    o, l = "", float("inf")
                    print(f"    {model} error: {type(e).__name__}: {str(e)[:80]}")
                outs.append(o)
                lats.append(l)
            # Pick the median-latency run's output for the judge
            order = sorted(range(N_RUNS), key=lambda k: lats[k])
            mid_idx = order[len(order) // 2]
            case_result["models"][model] = {
                "output": outs[mid_idx],
                "all_outputs": outs,
                "latencies": lats,
                "latency_median": statistics.median(lats) if lats else float("inf"),
                "rules": check_rules(case["text"], outs[mid_idx], case["lang"]),
            }
            print(f"    {model}: {case_result['models'][model]['latency_median']*1000:.0f}ms "
                  f"rules={sum(case_result['models'][model]['rules'].values())}/4")
            print(f"      OUT: {outs[mid_idx][:120]}{'...' if len(outs[mid_idx]) > 120 else ''}")

        # Blind judge with shuffled A/B labels
        if judge_model:
            shuffled = list(CANDIDATES)
            random.shuffle(shuffled)
            a_model, b_model = shuffled
            a_out = case_result["models"][a_model]["output"]
            b_out = case_result["models"][b_model]["output"]
            if a_out and b_out:
                try:
                    j = judge_pair(client, judge_model, case["text"], case["lang"], a_out, b_out)
                    winner_label = j.get("winner", "?")
                    winner_model = a_model if winner_label == "A" else (
                        b_model if winner_label == "B" else ("tie" if winner_label == "tie" else "?"))
                    case_result["judgment"] = {
                        "a_model": a_model, "b_model": b_model,
                        "label_winner": winner_label,
                        "model_winner": winner_model,
                        "reason": j.get("reason", "")[:200],
                    }
                    print(f"    judge: {winner_model}  ({j.get('reason', '')[:100]})")
                except Exception as e:
                    case_result["judgment"] = {"error": f"{type(e).__name__}: {str(e)[:80]}"}
                    print(f"    judge error: {case_result['judgment']['error']}")

        results.append(case_result)

    # ---- summary ----
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    for model in CANDIDATES:
        lats = [r["models"][model]["latency_median"] for r in results
                if r["models"][model]["latency_median"] != float("inf")]
        rule_passes = [sum(r["models"][model]["rules"].values()) for r in results]
        rule_all_pass = sum(1 for r in results if all(r["models"][model]["rules"].values()))
        if lats:
            print(f"\n{model}:")
            print(f"  latency  median: {statistics.median(lats)*1000:>5.0f}ms"
                  f"   mean: {statistics.mean(lats)*1000:>5.0f}ms"
                  f"   p95: {sorted(lats)[max(0, int(len(lats)*0.95)-1)]*1000:>5.0f}ms")
            print(f"  rules    all-pass: {rule_all_pass}/{len(results)}"
                  f"   avg score: {statistics.mean(rule_passes):.2f}/4")

    if judge_model and any("judgment" in r for r in results):
        wins = {m: 0 for m in CANDIDATES}
        ties = 0
        errors = 0
        for r in results:
            j = r.get("judgment", {})
            w = j.get("model_winner")
            if w in wins:
                wins[w] += 1
            elif w == "tie":
                ties += 1
            else:
                errors += 1
        print(f"\nJudge ({judge_model}) wins:")
        for m in CANDIDATES:
            print(f"  {m}: {wins[m]}")
        print(f"  tie: {ties}")
        if errors:
            print(f"  unparseable: {errors}")

    with open("bench_results.json", "w", encoding="utf-8") as f:
        json.dump({
            "candidates": CANDIDATES,
            "judge": judge_model,
            "n_runs": N_RUNS,
            "results": results,
        }, f, ensure_ascii=False, indent=2)
    print("\nFull per-case data -> bench_results.json")


if __name__ == "__main__":
    main()
