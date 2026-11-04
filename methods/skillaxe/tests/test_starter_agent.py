"""기존 파일의 노드가 실제로 실행되는지 검증한다. 원본 파일은 수정하지 않는다."""
import inspect
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from sql_agent.run import run_with_skill as run_agent
from methods.skillaxe.contracts import ExecutionPolicy, SkillVersion
from sql_agent.run import execute_sql
from methods.skillaxe.tests import test_execution as fixtures


class StarterAgentTests(unittest.TestCase):
    def setUp(self):
        fixtures.ExecutionTests.setUp(self)

    def test_original_generate_execute_and_route_really_run(self):
        from sql_agent import run as original
        observed = []

        def original_frames():
            return [frame.function for frame in inspect.stack()
                    if Path(frame.filename).resolve() == Path(original.__file__).resolve()]

        class Client(fixtures.SequenceClient):
            def complete(self, messages):
                observed.extend(original_frames())
                return super().complete(messages)

        def observe_execution(*args, **kwargs):
            observed.extend(original_frames())
            return execute_sql(*args, **kwargs)

        with patch("sql_agent.run.execute_sql", side_effect=observe_execution):
            trace = run_agent(self.task, None, self.database, Client("SELECT COUNT(*) FROM items"), ExecutionPolicy())
        self.assertIn("generate", observed)
        self.assertIn("execute", observed)
        self.assertEqual(trace.node_order, ("select_schema", "generate", "execute"))
        self.assertEqual(trace.engine, "sql_agent.run.GRAPH")
        self.assertEqual(trace.execution.rows, ((3,),))
        self.assertEqual(len(trace.agent_calls), 1)
        self.assertEqual(len(trace.execution_steps), 1)

    def test_observer_is_reset_after_execution(self):
        from sql_agent.run import current
        run_agent(self.task, None, self.database, fixtures.SequenceClient("SELECT 1"), ExecutionPolicy())
        self.assertIsNone(current())
        run_agent(self.task, None, self.database, fixtures.SequenceClient(RuntimeError("offline")), ExecutionPolicy())
        self.assertIsNone(current())

    def test_concurrent_runs_do_not_share_skill_or_client_bindings(self):
        first = SkillVersion("first", "L0", "First", "ONLY_FIRST_SKILL")
        second = SkillVersion("second", "L0", "Second", "ONLY_SECOND_SKILL")
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(run_agent, self.task, skill, self.database,
                                       fixtures.SequenceClient(sql), ExecutionPolicy())
                       for skill, sql in [(first, "SELECT 11"), (second, "SELECT 22")]]
            traces = [future.result() for future in futures]
        for trace, expected, own, other in [(traces[0], 11, first, second), (traces[1], 22, second, first)]:
            self.assertEqual(trace.execution.rows, ((expected,),))
            messages = str(trace.agent_call.messages)
            self.assertIn(own.body, messages)
            self.assertNotIn(other.body, messages)

    def test_original_fix_node_is_used_and_every_call_is_recorded(self):
        from sql_agent import run as starter

        skill = SkillVersion("count", "L0", "Count rows", "Use COUNT(*)")
        with patch.object(starter, "ROUTE", lambda state: "fix" if state["executions"] == 1 else starter.END):
            trace = run_agent(self.task, skill, self.database,
                              fixtures.SequenceClient("SELECT missing FROM items", "SELECT COUNT(*) FROM items"),
                              ExecutionPolicy())
        self.assertEqual(trace.node_order, ("select_schema", "generate", "execute", "fix", "execute"))
        self.assertEqual(len(trace.agent_calls), 2)
        self.assertEqual(len(trace.execution_steps), 2)
        self.assertEqual(trace.execution_steps[0].evidence.status, "error")
        self.assertEqual(trace.execution.rows, ((3,),))
        self.assertEqual(trace.sql, "SELECT COUNT(*) FROM items")
        self.assertIn("That SQL failed on SQLite", trace.agent_calls[1].messages[-1]["content"])
        for call in trace.agent_calls:
            self.assertIn(skill.body, str(call.messages))

    def test_original_extraction_semantics_are_not_silently_replaced(self):
        from sql_agent.run import extract_sql
        raw = "SELECT ';' AS punctuation"
        trace = run_agent(self.task, None, self.database, fixtures.SequenceClient(raw), ExecutionPolicy())
        self.assertEqual(trace.sql, extract_sql(raw))
        self.assertEqual(trace.sql, "SELECT '")
        self.assertEqual(trace.status, "error")
        self.assertEqual(trace.agent_call.response, raw)

    def test_original_fix_limit_is_preserved(self):
        from sql_agent import run as starter
        with patch.object(starter, "ROUTE", lambda state: "fix"):
            trace = run_agent(self.task, None, self.database, fixtures.SequenceClient(*(["SELECT 1"] * 6)),
                              ExecutionPolicy())
        self.assertEqual(len(trace.agent_calls), 6)  # 최초 생성 1회 + 원본 MAX_FIX=5
        self.assertEqual(len(trace.execution_steps), 6)
        self.assertIsNone(trace.graph_error_type)

    def test_graph_failure_before_generation_is_preserved_without_fake_call(self):
        from sql_agent import run as starter
        def fail_schema(state):
            raise RuntimeError("private failure")
        with patch.object(starter, "select_schema", fail_schema):
            broken_graph = starter.make_graph()
        with patch.object(starter, "GRAPH", broken_graph):
            trace = run_agent(self.task, None, self.database, fixtures.SequenceClient(), ExecutionPolicy())
        self.assertEqual(trace.status, "agent_error")
        self.assertIsNone(trace.agent_call)
        self.assertEqual(trace.agent_calls, ())
        self.assertEqual(trace.graph_error_type, "RuntimeError")


if __name__ == "__main__":
    unittest.main()
