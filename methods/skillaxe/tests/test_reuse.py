"""새로 복제한 동작이 아니라 기존 함수의 결과를 실제로 사용하는지 검증한다."""
import json
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from sql_agent.run import run_with_skill as run_agent
from methods.skillaxe.contracts import ExecutionPolicy, SkillVersion
from methods.skillaxe.dataset import PROJECT_ROOT, load_task
from methods.skillaxe.tests import test_execution as fixtures


class ReuseTests(unittest.TestCase):
    def setUp(self):
        fixtures.ExecutionTests.setUp(self)
        self.tasks_path = Path(self.tmp.name) / "tasks.json"
        self.tables_path = Path(self.tmp.name) / "tables.json"
        # 정답 SQL은 의도적으로 넣지만 로더 이후에는 어느 기록에도 없어야 한다.
        self.tasks_path.write_text(json.dumps([
            {"id": "q1", "question": "How many items?", "db_id": "sample", "gold_sql": "SECRET_GOLD"},
            {"id": "q2", "question": "List names", "db_id": "sample", "correctness": True},
        ]))
        self.tables_path.write_text(json.dumps([{
            "db_id": "sample", "table_names_original": ["items", "groups"],
            "column_names_original": [[-1, "*"], [0, "name"], [0, "group_id"], [1, "id"]],
            "column_types": ["text", "text", "number", "number"], "foreign_keys": [[2, 3]],
        }]))

    def test_agent_uses_existing_builder_and_hashes_its_actual_messages(self):
        from sql_agent import run as starter
        skill = SkillVersion("count", "L0", "Count rows", "Use COUNT(*)")
        client = fixtures.SequenceClient("SELECT 1", "SELECT 1", "SELECT 1")
        original = run_agent(self.task, None, self.database, client, ExecutionPolicy())
        # 기존 프롬프트가 달라졌을 때 복제본을 계속 쓰는 회귀를 잡는다.
        with patch.object(starter, "SYSTEM_PROMPT", "Fixture prompt from the existing agent"):
            baseline = run_agent(self.task, None, self.database, client, ExecutionPolicy())
            treated = run_agent(self.task, skill, self.database, client, ExecutionPolicy())
        expected = starter.build_messages(self.task.question, self.task.schema, [])
        expected[0]["content"] = "Fixture prompt from the existing agent"
        self.assertEqual(baseline.agent_call.messages, expected)
        self.assertEqual(treated.agent_call.messages[0], expected[0])
        self.assertEqual(treated.agent_call.messages[2:], expected[1:])
        self.assertIn(skill.body, treated.agent_call.messages[1]["content"])
        self.assertEqual(baseline.config_hash, treated.config_hash)
        self.assertNotEqual(original.config_hash, baseline.config_hash)

    def test_selected_task_uses_existing_schema_format_and_drops_gold(self):
        task = load_task(self.tasks_path, task_id="q1", tables_path=self.tables_path)
        self.assertEqual(task.schema, "table items: name text, group_id number\n"
                                     "table groups: id number\nforeign keys: items.group_id -> groups.id")
        self.assertEqual(task.question, "How many items?")
        self.assertNotIn("SECRET_GOLD", json.dumps(asdict(task)))
        self.assertNotIn("correctness", json.dumps(asdict(task)))

    def test_list_requires_exact_task_selection_and_rejects_duplicate_ids(self):
        for task_id in (None, "absent"):
            with self.subTest(task_id=task_id), self.assertRaises(ValueError):
                load_task(self.tasks_path, task_id=task_id, tables_path=self.tables_path)
        rows = json.loads(self.tasks_path.read_text())
        self.tasks_path.write_text(json.dumps([rows[0], rows[0]]))
        with self.assertRaises(ValueError):
            load_task(self.tasks_path, task_id="q1", tables_path=self.tables_path)

    def test_prepared_task_keeps_schema_without_reading_default_catalog(self):
        self.tasks_path.write_text(json.dumps(asdict(self.task)))
        loaded = load_task(self.tasks_path)
        self.assertEqual(loaded, self.task)
        with self.assertRaises(ValueError):
            load_task(self.tasks_path, task_id="different")

    def test_explicit_catalog_overrides_stale_prepared_schema(self):
        self.tasks_path.write_text(json.dumps(asdict(self.task)))
        loaded = load_task(self.tasks_path, tables_path=self.tables_path)
        self.assertIn("foreign keys: items.group_id -> groups.id", loaded.schema)

    def test_official_test_path_is_rejected_before_task_or_catalog_read(self):
        prohibited = PROJECT_ROOT / "data/test.json"
        # 실제 test 파일은 열지 않는다. 읽기를 시도하면 테스트가 먼저 실패한다.
        with patch.object(Path, "read_text", side_effect=AssertionError("must not read test data")):
            with self.assertRaises(ValueError):
                load_task(prohibited)
        with patch("methods.skillaxe.dataset.schema_text", side_effect=AssertionError("must not read test catalog")):
            with self.assertRaises(ValueError):
                load_task(self.tasks_path, task_id="q1", tables_path=prohibited)


if __name__ == "__main__":
    unittest.main()
