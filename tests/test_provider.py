import unittest
from unittest.mock import Mock, patch
import threading

import provider


class ProviderTests(unittest.TestCase):
    def test_stt_and_cleanup_share_http_transport(self):
        import llm
        import stt
        fake = Mock()
        fake.with_options.return_value = fake
        with patch.object(provider, "_client", None), patch.object(provider, "Groq", return_value=fake), \
                patch.object(provider.httpx, "Client") as transport, patch.dict(provider.os.environ, GROQ_API_KEY="test"), \
                patch.object(llm, "_client", None), patch.object(stt, "_client", None):
            self.assertIs(llm._get_client(), fake)
            self.assertIs(stt._get_client(), fake)
            transport.assert_called_once()
            self.assertEqual(transport.call_args.kwargs["limits"].keepalive_expiry, 120)

    def test_warmup_never_uploads_audio_and_stops_on_release(self):
        fake = Mock()
        fake.with_options.return_value = fake
        called = threading.Event()
        fake.models.list.side_effect = lambda: called.set()
        with patch.object(provider, "get_client", return_value=fake):
            stop = provider.warm_during_capture()
            self.assertTrue(called.wait(2))
            stop.set()
            with provider._warm_lock:
                pass
        fake.models.list.assert_called_once()
        fake.audio.transcriptions.create.assert_not_called()
        fake.chat.completions.create.assert_not_called()

    def test_failed_warmup_does_not_prevent_normal_client_use(self):
        fake = Mock()
        fake.with_options.return_value = fake
        called = threading.Event()

        def fail():
            called.set()
            raise RuntimeError("network unavailable")

        fake.models.list.side_effect = fail
        with patch.object(provider, "get_client", return_value=fake):
            stop = provider.warm_during_capture()
            self.assertTrue(called.wait(2))
            stop.set()
            with provider._warm_lock:
                pass
        fake.models.list.assert_called_once()


if __name__ == "__main__":
    unittest.main()
