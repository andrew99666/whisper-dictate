# Short Repetition Recognition Failure

The tested optimized pipeline is now the main Right Ctrl app. The previous
runtime and separate F9 runtime were stopped. Diagnostic audio, transcripts,
and raw result files remain private and are not published in this repository.

Status: reproduced; no reliable general fix validated. Date: 2026-10-13.

## Confirmed Findings

The user dictated "test test test" three times with F9. The first three logged raw Whisper outputs were "This is this.", "That's the story.", and "Test, test, test." Qwen did not change their words. Those audio files were not retained because recording saving was off.

With permission, recording saving was temporarily enabled for another three F9 tests:

| Saved clip | Duration | Raw Whisper Turbo | Qwen output |
|---|---:|---|---|
| dictation-1791890877857060500.wav | 1.37s | That's this. | That's this. |
| dictation-1791890880425944000.wav | 1.55s | Test, test, test. | Test, test, test. |
| dictation-1791890882641846600.wav | 1.32s | this this this | This this this |

The user listened to the third saved clip and confirmed three clear "test" words. This is a real recognition failure, not intentional repetition removed by cleanup. The text-only repetition guard cannot reconstruct words already misrecognized by ASR.

All three used Windows WASAPI, USB PnP microphone, 48kHz capture, and the existing Whisper Large V3 Turbo model. There was no silence rejection, clipping at full scale, API error, or prepared-result reuse in these dictations.

## Identical-Audio Probes

- Replaying the saved WAVs reproduced the wrong words. Original-snapshot and fast-copy encoders produce byte-identical FLAC uploads for all three files. No resampling/encoding algorithm change was introduced by the speed work.
- Whisper Turbo with 250ms added silence on each side, 3x gain, an English language hint, or a generic verbatim-repetition prompt still misrecognized the first and third clips. None of the prompts contained the expected phrase.
- Full Whisper V3 also failed the first and third clips, sometimes selecting an incorrect language or hallucinating unrelated text. Not adopted.
- The user separately authorized sending only these three clips to Google for an independent Gemini comparison. The live app was not switched to Google.
- Gemini 3.8 Flash recognized the second and third clips as "test test test", on both native WAV and the same 16kHz FLAC input Whisper received. It failed the first clip. Successful third-clip FLAC calls took about 2.6s and 3.2s; not a validated fast replacement.
- Gemini 3.5 Flash-Lite recognized the second clip but failed the first and third, including with a known-English hint. Not adopted. Initial diagnostic calls with an unsupported thinking setting returned HTTP 400; the setting was removed and calls rerun. These errors were in the diagnostic script, not the F9 app.
- Captures have non-silent endings. Truncation was considered, but it is not established as the cause. Merely adding synthetic silence does not repair missing speech.
- With separate permission, three new captures included a real 150ms post-release tail, with the release-point sample index saved in JSON. Full and release-cut audio were transcribed twice each, with alternating request order. First clip: "Let's test test" in both. Second: "Best test test" cut versus "Pest test test" full. Third: "test test test" in both. The extra tail did not correct any failing case. It was disabled after exactly three captures and the experimental runtime code was removed. Results remain in `speed_results_capture_boundary.json`; no microphone-setting change was deployed.

The confirmed failure is before Qwen, at the audio-to-text recognition stage. The precise acoustic reason the first clip is difficult across providers remains unresolved. Do not claim that the microphone is broken, that Qwen caused it, or that the issue has been fixed.

## State And Artifacts

The main app uses Whisper Turbo + Qwen temperature zero, with the existing tone
prompts and safeguards. The unchanged original app referenced above was the
baseline during diagnosis, before promotion. Audio saving is disabled; the
approved diagnostic WAVs remain private and gitignored.

Local result files and diagnosis scripts are retained with the private recordings,
not distributed in this repository. Google was used only for the explicitly
authorized diagnostic comparison, not in the live pipeline.

The earlier 2.02x median speed result covered four different recordings. It does not establish accuracy on short repeated-word utterances. This failing case must be included in future quality evaluations.
