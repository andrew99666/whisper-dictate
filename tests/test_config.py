import tempfile
import unittest
from pathlib import Path

import config


class PromotedDefaultsTests(unittest.TestCase):
    def test_missing_config_uses_fast_right_ctrl_defaults_without_saving_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = config.load(str(Path(folder) / "missing.toml"))
        self.assertEqual(cfg.hotkey, "ctrl_r")
        self.assertEqual(cfg.polish_model, "qwen/qwen3.8-27b")
        self.assertIsNone(cfg.mic_device)
        self.assertTrue(cfg.keep_mic_stream_open)
        self.assertTrue(cfg.warm_api_connection)
        self.assertFalse(cfg.prepare_while_recording)
        self.assertFalse(cfg.save_benchmark_recordings)
        self.assertFalse(cfg.restore_clipboard)
        self.assertEqual(cfg.polish_modes, config.DEFAULT_POLISH_MODES)


if __name__ == "__main__":
    unittest.main()
