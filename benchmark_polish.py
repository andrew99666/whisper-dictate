"""Live paired latency benchmark against Gemini or another Groq model."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import subprocess
import time
import types

from dotenv import load_dotenv

import config
import llm

SAMPLES = [
    ("short", "default", "Okay this is a test test this exactly dictation."),
    ("medium", "chat", "Hi Alex attaching the draft report please let me know if the team is happy with the changes and what you think the results look better than before but we should check the next two weeks before changing the plan."),
    ("long", "email", "Hi I manage three community centres and I'm looking for a calendar integration with a specific setup we already have our own registration system and website so we do not want a new booking platform or payment processing what we need is a feed that publishes our public events to the existing calendar please preserve the original dates and locations and do not create duplicate listings could you confirm whether your platform supports this and how pricing works for three centres happy to discuss the details on a call thanks Alex."),
]


def summary(rows: list[dict], field: str, providers=("gemini", "groq")) -> dict:
    result = {}
    for provider in providers:
        values = [row[field] for row in rows if row["provider"] == provider and field in row]
        if values:
            result[provider] = {
                "n": len(values), "median_ms": round(statistics.median(values), 1),
                "mean_ms": round(statistics.mean(values), 1),
                "min_ms": round(min(values), 1), "max_ms": round(max(values), 1),
            }
    if len(result) == 2:
        before, after = (result[name]["median_ms"] for name in providers)
        result["speedup"] = round(before / after, 3)
        result["latency_reduction_percent"] = round((1 - after / before) * 100, 1)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", default="25c32ea7f436d4a1a69b8ffec32934282a6dff70")
    parser.add_argument("--baseline-model", help="Compare another Groq model using the same settings instead of the Gemini Git baseline")
    parser.add_argument("--rounds", type=int, default=4)
    parser.add_argument("--audio", type=Path, help="Optional synthetic WAV to replay through STT + polish")
    parser.add_argument("--skip-text", action="store_true")
    parser.add_argument("--delay", type=float, default=0.0, help="Pause between rounds to avoid benchmark-induced rate limits")
    parser.add_argument("--output", type=Path, default=Path("bench_results.json"))
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error("rounds must be positive")
    if args.delay < 0:
        parser.error("delay must be nonnegative")
    load_dotenv()
    baseline_name = "baseline" if args.baseline_model else "gemini"
    baseline = types.ModuleType("polish_baseline")
    if args.baseline_model:
        source = Path(llm.__file__).read_text(encoding="utf-8")
    else:
        source = subprocess.check_output(["git", "show", f"{args.baseline_ref}:llm.py"], encoding="utf-8")
    exec(compile(source, "polish_baseline.py", "exec"), baseline.__dict__)
    if args.baseline_model:
        baseline.MODEL_ID = args.baseline_model
    cfg = config.load()
    modules = {baseline_name: baseline, "groq": llm}
    providers = tuple(modules)
    rows = []
    http_responses = []

    def record_response(resp):
        http_responses.append({"status": resp.status_code, **{
            name: resp.headers[name] for name in (
                "retry-after", "x-ratelimit-remaining-tokens", "x-ratelimit-remaining-requests",
            ) if name in resp.headers
        }})

    llm._get_client()._client.event_hooks["response"].append(record_response)
    if args.baseline_model and baseline._get_client()._client is not llm._get_client()._client:
        baseline._get_client()._client.event_hooks["response"].append(record_response)

    def run(provider, sample, mode, text, phase, stt_ms=None, language="English"):
        module = modules[provider]
        module._polish_cached.cache_clear()
        http_responses.clear()
        start = time.perf_counter()
        try:
            instruction = cfg.polish_modes[mode]
            if provider == "gemini":
                output = module.polish(text, language, instruction, None)
            else:
                output = module.polish(text, language, instruction)
            row = {"provider": provider, "sample": sample, "mode": mode, "phase": phase,
                   "polish_ms": round((time.perf_counter() - start) * 1000, 1), "output": output}
            if stt_ms is not None:
                row["stt_ms"] = round(stt_ms, 1)
                row["stt_plus_polish_ms"] = round(stt_ms + row["polish_ms"], 1)
        except Exception as exc:
            row = {"provider": provider, "sample": sample, "phase": phase,
                   "error_type": type(exc).__name__, "elapsed_ms": round((time.perf_counter() - start) * 1000, 1)}
        rows.append(row)
        if provider != "gemini":
            row["http_responses"] = list(http_responses)
        print(json.dumps(row, ensure_ascii=True), flush=True)

    for provider in modules:
        run(provider, "cold", "default", SAMPLES[0][2], "cold")
    for round_index in range(0 if args.skip_text else args.rounds):
        for sample, mode, text in SAMPLES:
            order = providers if round_index % 2 == 0 else providers[::-1]
            for provider in order:
                run(provider, sample, mode, text, "warm")
        time.sleep(args.delay)
    if args.audio:
        import soundfile as sf
        import stt
        audio, rate = sf.read(args.audio, dtype="float32")
        for round_index in range(args.rounds):
            start = time.perf_counter()
            txn = stt.transcribe(audio, rate)
            elapsed = (time.perf_counter() - start) * 1000
            order = providers if round_index % 2 == 0 else providers[::-1]
            for provider in order:
                run(provider, "audio_replay", "default", txn.text, "audio", elapsed, txn.language)
            time.sleep(args.delay)

    warm = [row for row in rows if row["phase"] == "warm"]
    audio_rows = [row for row in rows if row["phase"] == "audio"]
    report = {
        "baseline_ref": None if args.baseline_model else args.baseline_ref,
        "models": {name: module.MODEL_ID for name, module in modules.items()},
        "method": "Sequential alternating requests, identical prompts/text, local cache cleared per call; cold calls separate. Audio replay shares each measured STT result between models and excludes mic stop and paste.",
        "warm_polish": summary(warm, "polish_ms", providers),
        "by_sample": {sample: summary([row for row in warm if row["sample"] == sample], "polish_ms", providers) for sample, _, _ in SAMPLES},
        "audio_stt_plus_polish": summary(audio_rows, "stt_plus_polish_ms", providers),
        "errors": sum("error_type" in row for row in rows),
        "rows": rows,
    }
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "rows"}, indent=2), flush=True)


if __name__ == "__main__":
    main()
