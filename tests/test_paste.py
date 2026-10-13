import ctypes
import unittest
from unittest.mock import patch

import paste


class PasteTests(unittest.TestCase):
    @patch.object(paste.user32, "SendInput")
    def test_one_ordered_batch_contains_balanced_key_events(self, send):
        events = []

        def receive(count, inputs, size):
            self.assertEqual(count, 4)
            self.assertEqual(size, ctypes.sizeof(paste.INPUT))
            events.extend((inputs[i].ki.wVk, inputs[i].ki.dwFlags) for i in range(count))
            return count

        send.side_effect = receive
        self.assertTrue(paste._send_paste_chord_sendinput())
        self.assertEqual(events, [(paste.VK_LCONTROL, 0), (paste.VK_V, 0),
                                  (paste.VK_V, paste.KEYEVENTF_KEYUP),
                                  (paste.VK_LCONTROL, paste.KEYEVENTF_KEYUP)])

    @patch.object(paste, "_send_key")
    @patch.object(paste.user32, "SendInput", return_value=3)
    def test_partial_batch_releases_keys_without_duplicate_paste(self, send, release):
        with self.assertRaises(RuntimeError):
            paste._send_paste_chord_sendinput()
        self.assertEqual(release.call_args_list[0].args, (paste.VK_V,))
        self.assertEqual(release.call_args_list[1].args, (paste.VK_LCONTROL,))
        self.assertTrue(all(call.kwargs["key_up"] for call in release.call_args_list))

    @patch.object(paste, "_send_paste_chord")
    @patch.object(paste, "_safe_set_clipboard")
    @patch.object(paste, "_safe_get_clipboard", return_value="wrong clipboard")
    @patch.object(paste.time, "sleep")
    def test_failed_clipboard_write_never_sends_paste(self, sleep, get, copy, send):
        with self.assertRaises(RuntimeError):
            paste.paste_text("Expected text")
        send.assert_not_called()

    @patch.object(paste, "_send_paste_chord", return_value="sendinput")
    @patch.object(paste, "_safe_set_clipboard")
    @patch.object(paste, "_safe_get_clipboard", return_value="Expected text")
    @patch.object(paste.time, "sleep")
    def test_verified_synchronous_clipboard_write_has_no_fixed_wait(self, sleep, get, copy, send):
        paste.paste_text("Expected text")
        sleep.assert_not_called()
        send.assert_called_once()


if __name__ == "__main__":
    unittest.main()
