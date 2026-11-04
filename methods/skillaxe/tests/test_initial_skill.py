"""초기 생성은 한 번만 하고 이후 고정 파일을 재사용하는 계약을 검증한다."""
import json
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import Mock, patch

from llm import providers
from methods.skillaxe.generate_initial import generate_initial_skill
from methods.skillaxe.skills import load_skill
from methods.skillaxe.tests import test_execution as fixtures


class InitialSkillTests(unittest.TestCase):
    def setUp(self):
        fixtures.ExecutionTests.setUp(self)
        self.output = Path(self.tmp.name) / "frozen"

    def test_one_call_creates_reusable_skill_and_provenance_without_gold(self):
        response = json.dumps({"description": "Translate questions to SQLite.",
                               "body": "## Workflow\nInspect the schema before writing a query."})
        client = fixtures.SequenceClient(response)
        skill = generate_initial_skill([self.task], client, self.output)
        self.assertEqual(len(client.requests), 1)
        self.assertEqual(skill.version, "L0")
        self.assertEqual(load_skill(self.output / "L0.json"), skill)
        self.assertIn(skill.body, (self.output / "SKILL.md").read_text())
        record = json.loads((self.output / "generation.json").read_text())
        self.assertEqual(record["status"], "frozen")
        self.assertEqual(record["content_hash"], skill.content_hash)
        self.assertEqual(record["input_task_ids"], ["q1"])
        self.assertEqual(record["call"]["response"], response)
        self.assertNotIn("SECRET", json.dumps(client.requests))
        self.assertNotIn("gold_sql", json.dumps(client.requests))
        self.assertEqual(record["generation_calls"], 1)

    def test_existing_output_is_never_regenerated(self):
        self.output.mkdir()
        client = fixtures.SequenceClient()
        with self.assertRaises(FileExistsError):
            generate_initial_skill([self.task], client, self.output)
        self.assertEqual(client.requests, [])

    def test_invalid_response_is_preserved_without_a_repair_call(self):
        client = fixtures.SequenceClient("not JSON", "must never be requested")
        with self.assertRaises(ValueError):
            generate_initial_skill([self.task], client, self.output)
        self.assertEqual(len(client.requests), 1)
        self.assertFalse((self.output / "L0.json").exists())
        record = json.loads((self.output / "generation.json").read_text())
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["call"]["response"], "not JSON")

    def test_hash_mismatch_rejects_an_edited_frozen_skill(self):
        client = fixtures.SequenceClient(json.dumps({"description": "SQLite", "body": "Inspect schema."}))
        generate_initial_skill([self.task], client, self.output)
        path = self.output / "L0.json"
        raw = json.loads(path.read_text())
        raw["body"] = "Edited after freezing"
        path.write_text(json.dumps(raw))
        with self.assertRaisesRegex(ValueError, "hash"):
            load_skill(path)

    def test_single_request_client_disables_sdk_retries_and_preserves_usage(self):
        from methods.skillaxe.contracts import ModelSettings
        from llm.providers import Endpoint
        # SDK 네트워크 경계만 대체한다. 실제 complete 구현의 요청 옵션을 확인한다.
        client = object.__new__(providers.Client)
        client.single_request = True
        client.independent = True
        client.settings = ModelSettings(provider="openai", model="fixture")
        client._endpoint = Endpoint("openai", "https://fixture.invalid/v1", "fixture", "secret")
        sdk = Mock()
        sdk.with_options.return_value = sdk
        response = Mock()
        response.id = "response-fixture"
        response.choices = [Mock(finish_reason="stop", message=Mock(content='{"description":"x","body":"y"}'))]
        response.usage.prompt_tokens = 10
        response.usage.completion_tokens = 20
        response.usage.total_tokens = 30
        sdk.chat.completions.create.return_value = response
        with patch("llm.providers._client", return_value=sdk), patch.dict("os.environ", {}, clear=True):
            result = client.complete([{"role": "user", "content": "Generate one skill"}])
        self.assertIn('"body"', result)
        sdk.with_options.assert_called_once_with(max_retries=0)
        self.assertEqual(sdk.chat.completions.create.call_count, 1)
        self.assertEqual(client.response_metadata["usage"]["total_tokens"], 30)


if __name__ == "__main__":
    unittest.main()
