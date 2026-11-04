"""기존 함수와 공통 Client의 호출 정책을 SDK 경계에서 검증한다."""
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from llm import providers


class ProviderPolicyTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {
            "LLM_BASE_URL": "https://fixture.invalid/v1", "LLM_MODEL": "fixture",
        }, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.sdk = Mock()
        self.sdk.with_options.return_value = self.sdk
        self.sdk.chat.completions.create.return_value = SimpleNamespace(
            id="response", choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content="answer"))],
            usage=SimpleNamespace(prompt_tokens=2, completion_tokens=3, total_tokens=5))
        connection = patch("llm.providers._client", return_value=self.sdk)
        connection.start()
        self.addCleanup(connection.stop)

    def test_both_call_policies_write_provider_usage_log(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "usage.jsonl"
            with patch.dict(os.environ, {"LLM_USAGE_LOG": str(path)}):
                for single_request in (False, True):
                    client = providers.Client(role="improver", independent=True, single_request=single_request)
                    self.assertEqual(client.complete([{"role": "user", "content": "question"}]), "answer")
            entries = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(entries, [{"model": "fixture", "in": 2, "out": 3}] * 2)

    def test_single_request_failure_does_not_retry_or_leave_previous_metadata(self):
        client = providers.Client(role="agent", single_request=True)
        client.complete([])
        self.sdk.chat.completions.create.reset_mock()
        self.sdk.chat.completions.create.side_effect = RuntimeError("offline")
        with self.assertRaisesRegex(RuntimeError, "offline"):
            client.complete([])
        self.assertEqual(self.sdk.chat.completions.create.call_count, 1)
        self.assertEqual(client.response_metadata, {"sdk_max_retries": 0, "usage": None})

    def test_legacy_complete_keeps_parameter_adaptation(self):
        import httpx
        from openai import BadRequestError
        error = BadRequestError("unsupported parameter", response=httpx.Response(
            400, request=httpx.Request("POST", "https://fixture.invalid")),
            body={"error": {"param": "max_tokens"}})
        response = self.sdk.chat.completions.create.return_value
        self.sdk.chat.completions.create.side_effect = [error, response]
        with patch.dict(providers._quirks, {}, clear=True):
            result = providers.complete(providers.resolve("agent"), [], temperature=0, max_tokens=128)
        self.assertEqual(result, "answer")
        requests = self.sdk.chat.completions.create.call_args_list
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0].kwargs["max_tokens"], 128)
        self.assertEqual(requests[1].kwargs["max_completion_tokens"], 128)
        self.assertNotIn("max_tokens", requests[1].kwargs)


    def test_live_adapter_refuses_shared_cache_before_importing_sdk(self):
        with patch.dict(os.environ, {"LLM_CACHE": "existing-cache.sqlite"}):
            with self.assertRaisesRegex(ValueError, "LLM_CACHE"):
                providers.Client(role="agent", independent=True)

if __name__ == "__main__":
    unittest.main()

class StructuredResponseTests(unittest.TestCase):
    def test_structured_call_passes_schema_to_shared_request(self):
        from unittest.mock import patch,MagicMock
        from llm.providers import Client
        with patch.dict('os.environ',{'LLM_BASE_URL':'https://example.org/v1','LLM_MODEL':'model','LLM_API_KEY':'key','LLM_CACHE':'','LLM_BACKEND':'openai'}):
            c=Client(role='improver',independent=True)
            response=MagicMock();response.choices[0].message.content='{"rules":[]}'
            schema={'type':'object','properties':{'rules':{'type':'array','items':{'type':'string'}}},'required':['rules'],'additionalProperties':False}
            with patch('llm.providers._request',return_value=response) as request:
                self.assertEqual(c.complete_json([{'role':'user','content':'JSON'}],schema),' {"rules":[]}'.strip())
            self.assertEqual(request.call_args.args[2]['response_format']['json_schema']['schema'],schema)
            self.assertEqual(request.call_args.kwargs['sdk_max_retries'],0)
