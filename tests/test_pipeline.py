from concurrent.futures import Future
import sys
import time
import unittest
from unittest.mock import Mock, patch

import numpy as np

import main
from speculative import PreparedDictation
from stt import Transcription

sys.stderr = sys.__stderr__


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.audio = np.full(48000, 0.02, dtype=np.float32)
        self.txn = Transcription("raw words", "English")
        self.future = Future()
        now = time.perf_counter()
        self.future.set_result(PreparedDictation(self.txn, "Clean words", 1, 48000,
                                                now - 0.5, now, 200, 300))
        self.session = Mock()
        self.session.candidate.return_value = self.future
        self.session.requests = 1
        self.patches = [patch.object(main, "_set_state"), patch.object(main, "paste_text"),
                        patch.object(main, "transcribe", return_value=self.txn),
                        patch.object(main, "polish", return_value="Fallback clean words"),
                        patch.object(main, "toast"), patch.object(main, "logger")]
        self.state, self.paste, self.transcribe, self.polish, self.toast, self.logger = [p.start() for p in self.patches]
        for p in self.patches:
            self.addCleanup(p.stop)
        self.old_mode = main.CFG.polish_mode
        main.CFG.polish_mode = "default"
        self.addCleanup(setattr, main.CFG, "polish_mode", self.old_mode)

    def test_prepared_result_reaches_paste_without_repeating_cloud_requests(self):
        main._process(self.audio, 48000, speculation=self.session)
        self.transcribe.assert_not_called()
        self.polish.assert_not_called()
        self.assertEqual(self.paste.call_args.args[0], "Clean words")
        self.paste.assert_called_once()

    def test_invalid_preparation_reprocesses_full_recording(self):
        self.session.candidate.return_value = None
        main._process(self.audio, 48000, speculation=self.session)
        self.transcribe.assert_called_once()
        np.testing.assert_array_equal(self.transcribe.call_args.args[0], self.audio)
        self.polish.assert_called_once()
        self.assertEqual(self.paste.call_args.args[0], "Fallback clean words")

    def test_failed_preparation_falls_back_without_pasting_stale_words(self):
        failed = Future()
        failed.set_exception(RuntimeError("outage"))
        self.session.candidate.return_value = failed
        main._process(self.audio, 48000, speculation=self.session)
        self.transcribe.assert_called_once()
        self.assertEqual(self.paste.call_args.args[0], "Fallback clean words")

    def test_silence_skips_all_cloud_work_and_paste(self):
        main._process(np.zeros(48000, dtype=np.float32), 48000, speculation=self.session)
        self.session.candidate.assert_not_called()
        self.transcribe.assert_not_called()
        self.polish.assert_not_called()
        self.paste.assert_not_called()

    def test_raw_mode_remains_unpolished(self):
        main.CFG.polish_mode = "raw"
        self.session.candidate.return_value = None
        main._process(self.audio, 48000, speculation=self.session)
        self.polish.assert_not_called()
        self.assertEqual(self.paste.call_args.args[0], "raw words")


if __name__ == "__main__":
    unittest.main()
