# Dictation Speed Report

The optimized candidate is now the main app, using Right Ctrl. References to the
original being unchanged describe the historical paired benchmark. This run
predates the visual-only overlay refresh. Raw recordings and transcripts remain
private; [anonymized per-trial metrics](docs/benchmark-2026-10-13.json) are published.

Measured on 2026-10-13, on this Windows machine and Groq account.

## Result

The duplicate met the predefined **2x median release-to-insertion target** in the final run. It did not achieve 2x on every recording, or on mean latency. The margin above the median target is small; this is a measured result, not a guarantee for future provider load.

| Warm release-to-insertion | Previous 120B Pipeline | Optimized Qwen Pipeline |
|---|---:|---:|
| Median | 909.76ms | 451.36ms |
| Mean | 908.96ms | 477.25ms |
| 90th percentile, interpolated | 1089.57ms | 579.60ms |
| Maximum | 1184.78ms | 773.94ms |
| Trials | 12 | 12 |

Median speed ratio: **2.016x** (50.4% less waiting). Mean speed ratio: **1.905x**. No slow calls were removed.

| Recording | Original median | Duplicate median | Speed ratio |
|---|---:|---:|---:|
| 4.35s short test | 913.51ms | 422.93ms | 2.16x |
| 19.21s rambling/read-aloud test | 782.50ms | 585.07ms | 1.34x |
| 2.87s short test | 841.21ms | 387.80ms | 2.17x |
| 8.97s technical statement | 1001.86ms | 451.52ms | 2.22x |

The cold round was separate: four trials per implementation, median 1142.00ms original and 387.64ms duplicate. "Cold" here means the first application/client trials, not an uncached provider or newly booted machine.

## Method

- Four actual human F9 recordings replayed at their native duration, without trimming speech, adding silence, or extending the hotkey hold.
- Four rounds per recording, alternating original/candidate order. Round zero excluded from warm statistics by design, not because it was slow.
- Same audio for each paired comparison. The published JSON includes the
  historical source hashes, anonymized sample labels, and all trial timings,
  but excludes microphone recordings, transcripts, and machine-specific paths.
- Actual app `Recorder.stop`, full transcription/cleanup, clipboard copy and native SendInput. Local cleanup caches cleared before every trial. Minimum six seconds between speech requests avoids an artificial benchmark burst.
- A replay stream substitutes for the physical microphone. Original's 50ms close safeguard is included, but real hardware stop overhead is not; real original logs were about 63ms. Native duplicate lifecycle was tested separately.
- The receiver isolates only tagged injected keys with a Windows keyboard hook, then queues a paste into hidden Qt and timestamps `textChanged`. Physical input and foreground-app keys are not intercepted. This verifies full inserted text, but is not a timing measurement inside Notepad itself. The benchmark does temporarily use the Windows clipboard.
- Both real F9 tests in Notepad were separately confirmed by the user: automatic paste and intended wording. Their pipeline logs were 543ms and 434ms before the final deterministic cleanup setting.
- All **32 cold/warm insertions** matched the generated output exactly, with one paste per dictation. Required message content was retained in every final trial. No candidate fallback was needed in this run.

## What Changed

- At benchmark time, a separate F9 app was compared with the unchanged Right Ctrl
  GPT-OSS 120B app. The optimized implementation has since replaced the main app
  and uses Right Ctrl; the old runtime is no longer active.
- Same Groq Whisper Large v3 Turbo, microphone, lossless 16kHz upload, and all original tone/mode prompts.
- Qwen 3.8 27B cleanup, reasoning disabled and temperature zero. Provider exceptions fall back to GPT-OSS 120B. Conservative checks also trigger fallback for changed numbers, lost negations/uncertainty, and collapsed intentional repetitions.
- Shared Groq HTTP transport with a 120s client keep-alive. Model-list GETs warm the connection while recording, repeating every 30s for long holds. No audio is uploaded before release.
- Reused microphone stream; idle audio is discarded. The mic-in-use indicator can remain on. `keep_mic_stream_open = false` opts out.
- Verified clipboard write and one atomic Ctrl+V key batch; no fixed sleeps on the normal paste path. Dictated text stays on the clipboard.
- Silence/mute guards, COM-thread ownership, Qt main-thread ownership, and safe stream close remain intact.

Stage medians were stop 51ms to 2ms, transcription 305ms to 250ms, cleanup 441ms to 198ms, and paste-function completion 198ms to 6ms. These stage medians do not sum to the full-pipeline median. Original insertion occurs before its final key-up waits, so paste completion savings must not be substituted for insertion savings.

## Quality And Limitations

- Follow-up failure: three short "test test test" dictations produced different raw Whisper transcripts, before Qwen. Two of three saved re-tests were wrong; an independent Gemini comparison was not reliable across all three. No general fix is validated. See [SHORT_SPEECH_DIAGNOSIS.md](SHORT_SPEECH_DIAGNOSIS.md). The speed result below is not an accuracy guarantee on this case.

- The benchmarked version passed 40 tests and native microphone lifecycle checks.
  The current app passes 51 tests including the refreshed overlay. Original
  application and prompt hashes matched the preserved snapshot during the run.
- Twenty additional Qwen temperature-zero text checks passed content invariants for work messages, email, chat, technical names/commands, repeated words, Russian, and inert AI requests. This is limited coverage, not universal quality equivalence.
- Qwen at temperature 0.2 sometimes removed an uncertainty/read-aloud clause. That faster run was rejected. Temperature zero retained it in repeated probes and every final audio replay; the runtime guard adds another check.
- The final text-only quality sweep had multi-second slow calls under rapid requests. Those are retained in its JSON. Provider queueing, throttling, retries, audio length, and message length can still dominate latency.
- Qwen is a preview model, with higher token prices than 120B. See [Groq's model documentation](https://console.groq.com/docs/model/qwen/qwen3.8-27b). Fallback handles availability errors but can be slower.
- Pause preparation, streamed audio upload, and JSON-only transcription were tested but not adopted. Preparation made extra audio requests without helping the actual release pattern; the other probes did not consistently save meaningful time.
- Benchmark WAVs/results remain local and gitignored. New-recording saving is now disabled. Keep existing WAVs for reproduction.

## Reproduce

The original recordings and native replay harness are retained locally, not
published. A public clone cannot exactly rerun that private-audio trial. The
anonymized JSON supports independent recomputation of the reported statistics.

For new cleanup/transcription-stage comparisons using your own audio:

```powershell
python benchmark_polish.py --baseline-model openai/gpt-oss-120b --audio path/to/your.wav --rounds 4 --delay 2 --output bench_results.json
```

This makes live Groq calls; it does not measure or trigger native paste. Use
`--baseline-ref 25c32ea7f436d4a1a69b8ffec32934282a6dff70` without `--baseline-model`
for the historical Gemini integration (requires `google-genai` and a Google key).
Results vary with provider/network load. Stage timings must not be presented as
release-to-insertion timings.

## Other Products

Paid dictation products were not benchmarked. These measurements do not establish
that this app is faster than any or every paid tool.

