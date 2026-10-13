import unittest
from unittest.mock import Mock, patch

import audio


class InputDeviceTests(unittest.TestCase):
    def test_meter_reads_only_current_capture_without_changing_audio(self):
        recorder = audio.Recorder()
        chunk = audio.np.full((480, 1), 0.02, dtype=audio.np.float32)
        recorder._chunks = [chunk]
        self.assertEqual(recorder.meter_level(), 0)
        recorder._capturing = True
        self.assertAlmostEqual(recorder.meter_level(), 0.02, places=6)
        audio.np.testing.assert_array_equal(chunk, audio.np.full((480, 1), 0.02, dtype=audio.np.float32))
        self.assertEqual(len(recorder._chunks), 1)

    def test_meter_never_waits_on_capture_lock(self):
        recorder = audio.Recorder()
        with recorder._chunks_lock:
            self.assertEqual(recorder.meter_level(), 0)

    def test_warm_stop_detaches_audio_without_closing_stream(self):
        recorder = audio.Recorder()
        stream = Mock()
        recorder._stream = stream
        recorder._actual_rate = 48000
        recorder._capturing = True
        chunk = audio.np.ones((480, 1), dtype=audio.np.float32)
        recorder._on_audio(chunk, 480, None, None)
        captured, rate = recorder.stop()
        self.assertEqual(captured.size, 480)
        self.assertEqual(rate, 48000)
        stream.stop.assert_not_called()
        stream.close.assert_not_called()
        recorder._on_audio(chunk, 480, None, None)
        self.assertEqual(recorder.stop()[0].size, 0)
        with patch.object(audio.time, "sleep"):
            recorder.close()
        stream.stop.assert_called_once()
        stream.close.assert_called_once()

    def test_opt_out_retains_safe_close_delay(self):
        recorder = audio.Recorder(keep_stream_open=False)
        stream = Mock()
        recorder._stream = stream
        with patch.object(audio.time, "sleep") as sleep:
            recorder.stop()
        sleep.assert_called_once_with(0.05)
        stream.stop.assert_called_once()
        stream.close.assert_called_once()

    @patch.object(audio.sd, "query_devices")
    @patch.object(audio.sd, "InputStream")
    def test_start_reuses_active_stream_and_clears_previous_utterance(self, stream_factory, query):
        recorder = audio.Recorder(device=22)
        recorder._stream = Mock(active=True)
        recorder._opened_device = 22
        recorder._actual_rate = 48000
        recorder._chunks = [audio.np.ones((480, 1), dtype=audio.np.float32)]
        recorder.start()
        stream_factory.assert_not_called()
        self.assertTrue(recorder._capturing)
        self.assertEqual(recorder.stop()[0].size, 0)
        with patch.object(audio.time, "sleep"):
            recorder.close()

    @patch.object(audio.sd, "InputStream")
    @patch.object(audio.sd, "query_devices")
    @patch.object(audio.sd, "query_hostapis")
    def test_system_default_prefers_wasapi_input_without_changing_selection(self, apis, query, stream):
        apis.return_value = [
            {"name": "MME", "default_input_device": 1},
            {"name": "Windows WASAPI", "default_input_device": 22},
        ]
        query.return_value = {"name": "USB microphone", "max_input_channels": 1,
                              "default_samplerate": 48000, "hostapi": 1}
        recorder = audio.Recorder(device=None)
        recorder.start()
        self.assertIsNone(recorder.device)
        self.assertEqual(stream.call_args.kwargs["device"], 22)
        self.assertEqual(stream.call_args.kwargs["samplerate"], 48000)
        with patch.object(audio.time, "sleep"):
            recorder.stop()
            recorder.close()

    @patch.object(audio.sd, "query_devices")
    @patch.object(audio.sd, "query_hostapis")
    def test_missing_or_invalid_wasapi_default_uses_portaudio_default(self, apis, query):
        apis.return_value = [{"name": "MME", "default_input_device": 1}]
        self.assertIsNone(audio._default_wasapi_input())
        apis.return_value = [{"name": "Windows WASAPI", "default_input_device": -1}]
        self.assertIsNone(audio._default_wasapi_input())
        apis.return_value = [{"name": "Windows WASAPI", "default_input_device": 22}]
        query.return_value = {"max_input_channels": 0}
        self.assertIsNone(audio._default_wasapi_input())

    @patch.object(audio.sd, "query_devices")
    def test_default_device_uses_native_input_rate(self, query):
        query.return_value = {"default_samplerate": 48000}
        recorder = audio.Recorder(device=None)
        self.assertEqual(recorder._rate_for_device(None), 48000)
        query.assert_called_once_with(None, kind="input")

    @patch.object(audio.sd, "query_devices")
    def test_explicit_device_retains_native_rate(self, query):
        query.return_value = {"default_samplerate": 44100}
        self.assertEqual(audio.Recorder(device=22)._rate_for_device(22), 44100)
        query.assert_called_once_with(22, kind="input")

    @patch.object(audio.sd, "query_devices")
    def test_unavailable_device_information_uses_requested_rate(self, query):
        query.side_effect = RuntimeError("device unavailable")
        self.assertEqual(audio.Recorder(sample_rate=16000)._rate_for_device(None), 16000)

    @patch.object(audio.time, "sleep")
    @patch.object(audio.sd, "InputStream")
    @patch.object(audio.sd, "query_devices")
    def test_failed_explicit_device_falls_back_to_default_native_rate(self, query, stream, sleep):
        query.side_effect = lambda device, kind: {
            "default_samplerate": 48000 if device == 23 else 44100,
            "name": "BRIO" if device == 23 else "USB default",
        }
        working_stream = Mock()
        stream.side_effect = [RuntimeError("unavailable"), RuntimeError("unavailable"), working_stream]
        recorder = audio.Recorder(device=23)
        recorder.start()
        self.assertEqual(stream.call_args.kwargs["device"], None)
        self.assertEqual(stream.call_args.kwargs["samplerate"], 44100)
        self.assertEqual(recorder._actual_rate, 44100)
        recorder.stop()
        recorder.close()
        working_stream.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
