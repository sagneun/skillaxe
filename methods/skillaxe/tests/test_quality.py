"""LLM 응답만 고정하고 진단 흐름·부호·입력 경계는 실제 코드로 검사한다."""
import json
import unittest
from dataclasses import asdict, replace

from sql_agent.run import run_with_skill as run_agent
from methods.skillaxe.contracts import ExecutionPolicy, SkillVersion
from methods.skillaxe.diagnostics.quality import diagnose_quality
from methods.skillaxe.tests import test_execution as fixtures

SequenceClient = fixtures.SequenceClient


def direction(preference="A", **kwargs):
    return json.dumps({"preference": preference, "evidence": "A uses COUNT(*) for the requested row count.",
                       "uncertainty": False, "uncertainty_reason": "", **kwargs})


def magnitude(value=0.6, **kwargs):
    return json.dumps({"magnitude": value, "evidence": "The preferred SQL returns the requested aggregate.",
                       "uncertainty": False, "uncertainty_reason": "", **kwargs})


class QualityTests(unittest.TestCase):
    def setUp(self):
        # 같은 임시 DB 준비 절차를 공유한다. 기존 테스트 자체를 상속하지는 않는다.
        fixtures.ExecutionTests.setUp(self)
        self.skill = SkillVersion("count", "L0", "Counting", "Use COUNT(*) for row counts.")
        agent = SequenceClient("SELECT name FROM items", "SELECT COUNT(*) FROM items")
        self.baseline = run_agent(self.task, None, self.database, agent, ExecutionPolicy())
        self.treated = run_agent(self.task, self.skill, self.database, agent, ExecutionPolicy())

    def test_preference_is_mapped_back_to_skill_for_both_presentations(self):
        seen_positions = set()
        for seed in range(8):
            for preference in ("A", "B"):
                report = diagnose_quality(self.task, self.baseline, self.treated,
                                          SequenceClient(direction(preference), magnitude()), seed=seed)
                chosen = report.presentation[preference]["trace_id"]
                expected = 0.6 if chosen == self.treated.trace_id else -0.6
                self.assertAlmostEqual(report.score, expected)
                self.assertEqual(report.direction, 1 if expected > 0 else -1)
                self.assertEqual(report.magnitude, 0.6)
                self.assertEqual(report.status, "available")
                seen_positions.add(report.presentation["A"]["condition"])
        self.assertEqual(seen_positions, {"no_skill", "L0"})

    def test_tie_is_zero_and_does_not_spend_a_magnitude_call(self):
        report = diagnose_quality(self.task, self.baseline, self.treated, SequenceClient(direction("tie")))
        self.assertEqual((report.direction, report.magnitude, report.score), (0, 0.0, 0.0))
        self.assertEqual(len(report.calls), 1)
        self.assertEqual(report.status, "available")

    def test_judge_sees_only_allowed_evidence_and_magnitude_is_conditioned(self):
        judge = SequenceClient(direction("B", uncertainty=True, uncertainty_reason="Only a sample is visible."), magnitude())
        report = diagnose_quality(self.task, self.baseline, self.treated, judge)
        first = json.loads(judge.requests[0][-1]["content"])
        second = json.loads(judge.requests[1][-1]["content"])
        self.assertEqual(first["task"]["question"], self.task.question)
        self.assertIn("sql", first["responses"]["A"])
        self.assertIn("rows_truncated", first["responses"]["A"]["execution"])
        self.assertEqual(second["preferred"], "B")
        self.assertEqual(second["direction_evidence"], "A uses COUNT(*) for the requested row count.")
        encoded = json.dumps(first)
        for forbidden in ("SECRET", "gold_sql", "correctness", "mismatch", self.skill.body,
                          "no_skill", "trace_id", "agent_call"):
            self.assertNotIn(forbidden, encoded)
        self.assertTrue(report.uncertainty)
        self.assertIn("Only a sample is visible.", report.uncertainty_reasons)
        self.assertEqual(len(report.calls), 2)

    def test_judge_failure_is_unavailable_not_tie(self):
        for reply in [RuntimeError("SECRET_KEY"), "not JSON", direction("C"),
                      direction(uncertainty="false"), direction(evidence=""),
                      direction(uncertainty=True, uncertainty_reason="")]:
            with self.subTest(reply=reply):
                report = diagnose_quality(self.task, self.baseline, self.treated, SequenceClient(reply))
                self.assertEqual(report.status, "unavailable")
                self.assertIsNone(report.score)
                self.assertTrue(report.error)
                self.assertNotIn("SECRET_KEY", json.dumps(asdict(report)))

    def test_bad_magnitude_retains_direction_record_but_has_no_final_score(self):
        for value in [float("nan"), float("inf"), -0.1, 1.1, True, "0.6"]:
            with self.subTest(value=value):
                report = diagnose_quality(self.task, self.baseline, self.treated,
                                          SequenceClient(direction(), magnitude(value)))
                self.assertEqual(report.status, "unavailable")
                self.assertIsNone(report.score)
                self.assertEqual(len(report.calls), 2)
                self.assertIn(report.direction, (-1, 1))
                json.dumps(asdict(report), allow_nan=False)

    def test_huge_integer_magnitude_does_not_lose_judge_records(self):
        report = diagnose_quality(self.task, self.baseline, self.treated,
                                  SequenceClient(direction(), magnitude(10 ** 400)))
        self.assertEqual(report.status, "unavailable")
        self.assertIsNone(report.score)
        self.assertEqual(len(report.calls), 2)
        self.assertIn(report.direction, (-1, 1))

    def test_generated_invalid_sql_is_still_observable_failure(self):
        invalid = run_agent(self.task, None, self.database, SequenceClient("SELECT missing_column FROM items"),
                            ExecutionPolicy())
        report = diagnose_quality(self.task, invalid, self.treated, SequenceClient(direction(), magnitude()))
        self.assertEqual(invalid.status, "error")
        self.assertEqual(report.status, "available")

    def test_graph_failure_without_model_output_is_unavailable(self):
        failed = replace(self.baseline, status="agent_error", agent_call=None, agent_calls=(),
                         execution=None, graph_error_type="RuntimeError")
        report = diagnose_quality(self.task, failed, self.treated, SequenceClient())
        self.assertEqual(report.status, "unavailable")
        self.assertIsNone(report.score)
        self.assertEqual(report.calls, ())

    def test_mismatched_experiments_are_rejected_before_judging(self):
        for change in [{"task_id": "other"}, {"input_hash": "different"}, {"db_hash": "different"},
                       {"replicate": 2}, {"config_hash": "different"}, {"skill_hash": None},
                       {"trace_id": self.baseline.trace_id}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                diagnose_quality(self.task, self.baseline, replace(self.treated, **change), SequenceClient())


if __name__ == "__main__":
    unittest.main()
