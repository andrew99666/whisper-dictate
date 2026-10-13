import unittest
from unittest.mock import Mock, patch
import threading

import numpy as np

import speculative
from stt import Transcription


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.voice = np.full((4800, 1), 0.02, dtype=np.float32)
        self.quiet = np.zeros((4800, 1), dtype=np.float32)
        self.session = speculative.SpeculativeSession("default", "Tone prompt")
        self.stt_patch = patch.object(speculative, "transcribe", return_value=Transcription("raw words", "English"))
        self.polish_patch = patch.object(speculative, "polish", return_value="Clean words")
        self.transcribe = self.stt_patch.start()
        self.polish = self.polish_patch.start()
        self.addCleanup(self.stt_patch.stop)
        self.addCleanup(self.polish_patch.stop)

    def prepare(self):
        self.session.push(self.voice, 48000)
        self.session.push(self.quiet, 48000)
        audio = np.concatenate((self.voice, self.quiet)).reshape(-1)
        future = self.session.candidate(audio, 48000, "default", "Tone prompt")
        self.assertIsNotNone(future)
        future.result(timeout=2)
        return audio, future

    def test_complete_preparation_reuses_only_final_text_and_exact_audio(self):
        audio, future = self.prepare()
        self.assertEqual(future.result().text, "Clean words")
        sent_audio = self.transcribe.call_args.args[0]
        np.testing.assert_array_equal(sent_audio[:audio.size], audio)
        self.polish.assert_called_once_with("raw words", "English", "Tone prompt")

    def test_new_speech_invalidates_even_completed_result(self):
        audio, future = self.prepare()
        self.session.push(self.voice, 48000)
        final = np.concatenate((audio, self.voice.reshape(-1)))
        self.assertIsNone(self.session.candidate(final, 48000, "default", "Tone prompt"))

    def test_quiet_partial_frame_with_possible_speech_rejects_reuse(self):
        audio, future = self.prepare()
        partial = np.full((17, 1), 0.0007, dtype=np.float32)
        self.session.push(partial, 48000)
        final = np.concatenate((audio, partial.reshape(-1)))
        self.assertIsNone(self.session.candidate(final, 48000, "default", "Tone prompt"))

    def test_changed_mode_prompt_or_missing_audio_never_reuses_result(self):
        audio, future = self.prepare()
        self.assertIsNone(self.session.candidate(audio, 48000, "email", "Tone prompt"))
        self.assertIsNone(self.session.candidate(audio, 48000, "default", "New prompt"))
        self.assertIsNone(self.session.candidate(audio[:-1], 48000, "default", "Tone prompt"))

    def test_silence_never_starts_rpc_and_unsupported_rate_falls_back(self):
        self.session.push(self.quiet, 48000)
        self.transcribe.assert_not_called()
        self.assertIsNone(self.session.candidate(self.quiet.reshape(-1), 48000, "default", "Tone prompt"))
        self.session.push(self.voice, 44100)
        self.session.push(self.quiet, 44100)
        self.transcribe.assert_not_called()

    def test_resumed_speech_during_stt_prevents_polishing_stale_transcript(self):
        started = threading.Event()
        resume = threading.Event()

        def slow_stt(*args):
            started.set()
            resume.wait(2)
            return Transcription("partial sentence", "English")

        self.transcribe.side_effect = slow_stt
        self.session.push(self.voice, 48000)
        self.session.push(self.quiet, 48000)
        future = self.session._future
        self.assertTrue(started.wait(2))
        self.session.push(self.voice, 48000)
        resume.set()
        with self.assertRaises(speculative.StalePreparation):
            future.result(timeout=2)
        self.polish.assert_not_called()

    def test_provider_failure_is_exposed_for_complete_recording_fallback(self):
        self.transcribe.side_effect = RuntimeError("provider unavailable")
        self.session.push(self.voice, 48000)
        self.session.push(self.quiet, 48000)
        with self.assertRaises(RuntimeError):
            self.session._future.result(timeout=2)


if __name__ == "__main__":
    unittest.main()
