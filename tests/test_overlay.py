import math
import os
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

import overlay


class OverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["overlay-test", "-platform", "offscreen"])
        fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for name in ("segoeui.ttf", "segoeuib.ttf"):
            if (fonts / name).exists():
                QFontDatabase.addApplicationFont(str(fonts / name))

    def setUp(self):
        self.meter = Mock(return_value=0.02)
        self.widget = overlay._OverlayWidget(self.meter)
        self.addCleanup(self.widget.close)

    def test_window_remains_click_through_and_non_activating(self):
        flags = self.widget.windowFlags()
        self.assertTrue(flags & Qt.WindowTransparentForInput)
        self.assertTrue(flags & Qt.WindowDoesNotAcceptFocus)
        self.assertTrue(self.widget.testAttribute(Qt.WA_ShowWithoutActivating))
        self.assertEqual(self.widget.focusPolicy(), Qt.NoFocus)

    def test_states_keep_fixed_dimensions_and_idle_stops_animation(self):
        size = self.widget.size()
        for state in ("recording", "processing", "muted", "idle"):
            self.widget.set_state_slot(state)
            self.assertEqual(self.widget.size(), size)
            self.assertEqual(self.widget._timer.isActive(), state in ("recording", "processing"))
            self.assertEqual(self.widget.isVisible(), state != "idle")

    def test_meter_is_polled_only_while_recording(self):
        self.widget.set_state_slot("processing")
        self.widget._tick()
        self.meter.assert_not_called()
        self.widget.set_state_slot("recording")
        self.widget._tick()
        self.meter.assert_called_once()
        self.assertGreater(self.widget._pill._levels[-1], 0)

    def test_failed_or_nonfinite_meter_does_not_break_indicator(self):
        self.widget.set_state_slot("recording")
        for result in (float("nan"), float("inf"), -1):
            self.meter.return_value = result
            self.widget._tick()
            self.assertTrue(math.isfinite(self.widget._pill._levels[-1]))
        self.meter.side_effect = RuntimeError("device changed")
        self.widget._tick()
        self.assertEqual(self.widget._pill._levels[-1], 0)

    def test_processing_animation_changes_rendered_pixels(self):
        self.widget.set_state_slot("processing")
        self.widget._pill.set_frame(0)
        before = self.widget.grab().toImage()
        self.widget._pill.set_frame(0.4)
        after = self.widget.grab().toImage()
        self.assertFalse(before == after)

    def test_recording_meter_and_clock_reset_for_next_dictation(self):
        self.widget.set_state_slot("recording")
        self.widget._pill.set_frame(62, 0.03)
        self.widget.set_state_slot("idle")
        self.widget.set_state_slot("recording")
        self.assertEqual(self.widget._pill._elapsed, 0)
        self.assertTrue(all(value == 0 for value in self.widget._pill._levels))

    def test_worker_state_change_is_queued_to_qt(self):
        facade = overlay.Overlay()
        self.addCleanup(facade._widget.close)
        thread = threading.Thread(target=facade.set_state, args=("recording",))
        thread.start()
        thread.join()
        self.assertEqual(facade._widget._state, "idle")
        self.app.processEvents()
        self.assertEqual(facade._widget._state, "recording")

    def test_long_duration_clock_has_hour_format(self):
        self.assertEqual(overlay._clock(0), "0:00")
        self.assertEqual(overlay._clock(62), "1:02")
        self.assertEqual(overlay._clock(3661), "1:01:01")


if __name__ == "__main__":
    unittest.main()
