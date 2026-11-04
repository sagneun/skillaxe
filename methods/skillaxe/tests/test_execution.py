"""정답 정보 차단과 실제 SQLite 동작을 검증한다. 공식 데이터는 사용하지 않는다."""
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from dataclasses import asdict
from pathlib import Path

from methods.skillaxe.contracts import ExecutionPolicy, ModelSettings, SkillVersion, TaskInput
from sql_agent.run import execute_sql
from methods.skillaxe.records import write_json
from sql_agent.run import run_with_skill as run_agent


class SequenceClient:
    """외부 네트워크만 대체한다. SQL 실행·진단 계산·기록은 실제 코드를 사용한다."""

    def __init__(self, *responses):
        self.settings = ModelSettings(provider="fixture", model="fixture", mode="mock")
        self.responses = iter(responses)
        self.requests = []

    def complete(self, messages):
        self.requests.append(messages)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.database = Path(self.tmp.name) / "sample.sqlite"
        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.execute("CREATE TABLE items (name TEXT, amount INTEGER)")
            conn.executemany("INSERT INTO items VALUES (?, ?)", [("a", 1), ("b", 2), ("c", 3)])
        self.task = TaskInput.from_record({
            "task_id": "q1", "question": "How many items are there?", "db_id": "sample",
            "schema": "table items: name TEXT, amount INTEGER",
            "gold_sql": "SECRET_GOLD", "correctness": True, "mismatch": "SECRET_MISMATCH",
        })

    def test_allowlist_drops_gold_and_unrelated_metadata(self):
        serialized = json.dumps(asdict(self.task))
        self.assertNotIn("SECRET", serialized)
        self.assertNotIn("correctness", serialized)
        other = TaskInput.from_record({**asdict(self.task), "gold_sql": "DIFFERENT"})
        self.assertEqual(self.task.input_hash, other.input_hash)
        with self.assertRaises(ValueError):
            TaskInput.from_record({"task_id": "x", "question": 123, "schema": "x", "db_id": "db"})

    def test_read_only_query_returns_columns_and_explicit_truncation(self):
        result = execute_sql(self.database, "SELECT * FROM items ORDER BY amount", ExecutionPolicy(row_limit=2))
        self.assertEqual(result.status, "success")
        self.assertEqual(result.columns, ("name", "amount"))
        self.assertEqual(result.rows, (("a", 1), ("b", 2)))
        self.assertTrue(result.rows_truncated)
        result = execute_sql(self.database, "SELECT COUNT(*) AS n FROM items", ExecutionPolicy())
        self.assertEqual(result.rows, ((3,),))
        self.assertFalse(result.rows_truncated)

    def test_sql_writes_attach_and_pragmas_are_denied(self):
        original = self.database.read_bytes()
        for sql in ["DELETE FROM items", "DROP TABLE items", "PRAGMA user_version=1",
                    "ATTACH DATABASE ':memory:' AS other", "SELECT 1; DELETE FROM items"]:
            with self.subTest(sql=sql):
                self.assertEqual(execute_sql(self.database, sql, ExecutionPolicy()).status, "error")
        self.assertEqual(self.database.read_bytes(), original)

    def test_timeout_is_not_a_success_or_empty_answer(self):
        result = execute_sql(self.database,
            "WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n) SELECT sum(x) FROM n",
            ExecutionPolicy(timeout_seconds=0.01))
        self.assertEqual(result.status, "timeout")
        self.assertTrue(result.error)

    def test_cells_are_json_safe_and_truncation_is_visible(self):
        result = execute_sql(self.database, "SELECT 'abcdefgh', x'FF00'", ExecutionPolicy(max_cell_chars=4))
        self.assertTrue(result.cells_truncated)
        self.assertEqual(result.rows[0][0], "abcd")
        self.assertEqual(result.rows[0][1], {"type": "blob", "hex": "ff00"})
        json.dumps(asdict(result), allow_nan=False)

    def test_policy_rejects_invalid_limits(self):
        for kwargs in [{"row_limit": 0}, {"row_limit": True}, {"timeout_seconds": float("nan")},
                       {"timeout_seconds": -1}, {"max_cell_chars": 0}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                ExecutionPolicy(**kwargs)

    def test_paired_agent_changes_only_skill_and_uses_starter_extraction(self):
        client = SequenceClient("SELECT 7 AS n", "```sql\nSELECT 7 AS n;\n```")
        skill = SkillVersion(skill_id="count", version="L0", description="Counting", body="Use COUNT(*) for row counts.")
        baseline = run_agent(self.task, None, self.database, client, ExecutionPolicy())
        treated = run_agent(self.task, skill, self.database, client, ExecutionPolicy())
        self.assertEqual(baseline.execution.rows, ((7,),))
        self.assertEqual(treated.execution.rows, ((7,),))
        self.assertEqual(baseline.config_hash, treated.config_hash)
        self.assertEqual(baseline.db_hash, treated.db_hash)
        self.assertNotEqual(baseline.trace_id, treated.trace_id)
        self.assertEqual(client.requests[0][0], client.requests[1][0])
        self.assertEqual(client.requests[0][-1], client.requests[1][-1])
        self.assertIn(skill.body, client.requests[1][1]["content"])
        self.assertNotIn("SECRET", json.dumps(client.requests))
        self.assertEqual(treated.skill_hash, skill.content_hash)

    def test_generation_failure_stays_in_trace_without_secret_exception_text(self):
        trace = run_agent(self.task, None, self.database,
                          SequenceClient(RuntimeError("SECRET_API_KEY")), ExecutionPolicy())
        self.assertEqual(trace.status, "generation_error")
        self.assertIsNone(trace.execution)
        self.assertEqual(trace.agent_call.status, "error")
        self.assertNotIn("SECRET_API_KEY", json.dumps(asdict(trace)))

    def test_missing_database_is_not_created(self):
        missing = self.database.parent / "missing.sqlite"
        result = execute_sql(missing, "SELECT 1", ExecutionPolicy())
        self.assertEqual(result.status, "error")
        self.assertFalse(missing.exists())


    def test_json_writer_never_overwrites_by_default_or_writes_invalid_json(self):
        target = Path(self.tmp.name) / "value.json"
        write_json(target, {"status": "good"})
        with self.assertRaises(FileExistsError):
            write_json(target, {"status": "replaced"})
        with self.assertRaises(ValueError):
            write_json(target, {"bad": float("nan")}, replace=True)
        self.assertEqual(json.loads(target.read_text()), {"status": "good"})

if __name__ == "__main__":
    unittest.main()
