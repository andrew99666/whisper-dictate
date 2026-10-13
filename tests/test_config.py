import tempfile
import re
import unittest
from pathlib import Path

import config
import llm


class PromotedDefaultsTests(unittest.TestCase):
    def test_model_instructions_avoid_ambiguous_cleanup_word(self):
        prompts = list(config.DEFAULT_POLISH_MODES.values()) + [llm.SYSTEM_INSTRUCTION]
        for prompt in prompts:
            self.assertIsNone(re.search(r"\bpolish\b", prompt, re.IGNORECASE))

    def test_editing_modes_preserve_language_but_translation_mode_is_explicit(self):
        for mode in ("default", "email", "chat", "code"):
            self.assertIn(config.LANGUAGE_PRESERVATION_RULE, config.DEFAULT_POLISH_MODES[mode])
        self.assertIn(config.LANGUAGE_PRESERVATION_RULE, llm.SYSTEM_INSTRUCTION)
        self.assertNotIn(config.LANGUAGE_PRESERVATION_RULE, config.DEFAULT_POLISH_MODES["translate_en"])
        self.assertIn("output is ALWAYS in English", config.DEFAULT_POLISH_MODES["translate_en"])

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
