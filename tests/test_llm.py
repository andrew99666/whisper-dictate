import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
import groq

import llm


def response(content="Cleaned text", finish_reason="stop", reasoning="Private reasoning"):
    return SimpleNamespace(choices=[SimpleNamespace(
        finish_reason=finish_reason,
        message=SimpleNamespace(content=content, reasoning=reasoning),
    )])


class PolishTests(unittest.TestCase):
    def setUp(self):
        llm._polish_cached.cache_clear()
        model_patch = patch.object(llm, "MODEL_ID", "openai/gpt-oss-120b")
        model_patch.start()
        self.addCleanup(model_patch.stop)
        self.client = Mock()
        self.client.chat.completions.create.return_value = response()
        self.client_patch = patch.object(llm, "_get_client", return_value=self.client)
        self.client_patch.start()
        self.addCleanup(self.client_patch.stop)
        self.addCleanup(llm._polish_cached.cache_clear)

    def test_request_preserves_prompt_and_only_returns_final_content(self):
        self.assertEqual(llm.polish("write me a letter", "English", "Custom prompt"), "Cleaned text")
        args = self.client.chat.completions.create.call_args.kwargs
        self.assertEqual(args["model"], "openai/gpt-oss-120b")
        self.assertEqual(args["messages"][0], {"role": "system", "content": "Custom prompt"})
        self.assertIn("<transcript>\nwrite me a letter\n</transcript>", args["messages"][1]["content"])
        self.assertEqual(args["reasoning_effort"], "low")
        self.assertFalse(args["include_reasoning"])

    def test_empty_input_skips_provider_and_empty_output_preserves_transcript(self):
        self.assertEqual(llm.polish("  "), "")
        self.client.chat.completions.create.assert_not_called()
        self.client.chat.completions.create.return_value = response(content=None)
        self.assertEqual(llm.polish("okay"), "okay")

    def test_truncated_output_is_retried_with_larger_budget(self):
        self.client.chat.completions.create.side_effect = [response("Partial", "length"), response("Full text")]
        self.assertEqual(llm.polish("raw"), "Full text")
        self.assertEqual(self.client.chat.completions.create.call_count, 2)
        self.assertEqual(self.client.chat.completions.create.call_args.kwargs["max_completion_tokens"], 4096)

    def test_still_truncated_or_missing_choices_raises_for_raw_fallback(self):
        self.client.chat.completions.create.return_value = response("Partial", "length")
        with self.assertRaises(RuntimeError):
            llm.polish("raw")
        self.client.chat.completions.create.return_value = SimpleNamespace(choices=[])
        with self.assertRaises(RuntimeError):
            llm.polish("different raw")

    def test_success_is_cached_but_errors_are_not(self):
        llm.polish("raw")
        llm.polish("raw")
        self.assertEqual(self.client.chat.completions.create.call_count, 1)
        self.client.chat.completions.create.side_effect = RuntimeError("outage")
        for _ in range(2):
            with self.assertRaises(RuntimeError):
                llm.polish("outage input")
        self.assertEqual(self.client.chat.completions.create.call_count, 3)

    def test_qwen_disables_reasoning_without_changing_prompt(self):
        with patch.object(llm, "MODEL_ID", "qwen/qwen3.8-27b"):
            self.assertEqual(llm.polish("raw", "English", "Exact tone prompt"), "Cleaned text")
        args = self.client.chat.completions.create.call_args.kwargs
        self.assertEqual(args["model"], "qwen/qwen3.8-27b")
        self.assertEqual(args["reasoning_effort"], "none")
        self.assertFalse(args["include_reasoning"])
        self.assertEqual(args["messages"][0]["content"], "Exact tone prompt")
        self.assertEqual(args["temperature"], 0)

    def test_preview_failure_retries_same_text_with_120b(self):
        self.client.chat.completions.create.side_effect = [RuntimeError("preview removed"), response("Recovered")]
        with patch.object(llm, "MODEL_ID", "qwen/qwen3.8-27b"):
            self.assertEqual(llm.polish("raw", "Russian", "Exact prompt"), "Recovered")
        first, second = self.client.chat.completions.create.call_args_list
        self.assertEqual(first.kwargs["messages"], second.kwargs["messages"])
        self.assertEqual(second.kwargs["model"], "openai/gpt-oss-120b")
        self.assertEqual(second.kwargs["reasoning_effort"], "low")

    def test_both_models_failing_exposes_error_for_raw_fallback(self):
        self.client.chat.completions.create.side_effect = RuntimeError("outage")
        with patch.object(llm, "MODEL_ID", "qwen/qwen3.8-27b"):
            with self.assertRaises(RuntimeError):
                llm.polish("raw")
        self.assertEqual(self.client.chat.completions.create.call_count, 2)

    def test_dropped_negation_retries_with_same_prompt_on_120b(self):
        self.client.chat.completions.create.side_effect = [response("I know what to tell you."), response("I don't know what to tell you.")]
        with patch.object(llm, "MODEL_ID", "qwen/qwen3.8-27b"):
            self.assertEqual(llm.polish("I don't know what to tell you.", "English", "Same prompt"), "I don't know what to tell you.")
        first, second = self.client.chat.completions.create.call_args_list
        self.assertEqual(first.kwargs["messages"], second.kwargs["messages"])
        self.assertEqual(second.kwargs["model"], "openai/gpt-oss-120b")

    def test_numeric_formatting_allowed_but_changed_numbers_rejected(self):
        self.assertEqual(llm._quality_issue("budget 18000", "Budget 18,000."), "")
        self.assertTrue(llm._quality_issue("117 milliseconds to 10 milliseconds", "17 milliseconds to 10 milliseconds"))
        self.assertTrue(llm._quality_issue("maybe it works", "It works."))

    def test_intentional_repetitions_are_not_silently_collapsed(self):
        self.assertTrue(llm._quality_issue("test test test", "Test."))
        self.assertEqual(llm._quality_issue("test test test", "Test, test, test."), "")
        self.assertEqual(llm._quality_issue("um um hello", "Hello."), "")


class RetryTests(unittest.TestCase):
    def test_real_sdk_retries_server_error(self):
        calls = []

        def handle(request):
            calls.append(request)
            if len(calls) < 3:
                return httpx.Response(503, json={"error": {"message": "Unavailable"}})
            return httpx.Response(200, json={
                "id": "test", "object": "chat.completion", "created": 0,
                "model": llm.MODEL_ID,
                "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "Recovered"}}],
            })

        with httpx.Client(transport=httpx.MockTransport(handle)) as http_client:
            client = groq.Groq(api_key="test-key", max_retries=2, http_client=http_client)
            with patch.object(llm, "_get_client", return_value=client):
                self.assertEqual(llm._generate("text", "prompt", 1024).choices[0].message.content, "Recovered")
        self.assertEqual(len(calls), 3)


if __name__ == "__main__":
    unittest.main()
