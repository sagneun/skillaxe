import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dashboard.loader import load_run, list_runs

class LoaderTests(unittest.TestCase):
    def test_three_conditions_and_partial_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);run=root/'round-2-test';run.mkdir()
            (run/'manifest.json').write_text(json.dumps({'round':2,'status':'complete'}))
            for stage,score in [('no_skill',60),('parent',66),('candidate',69)]:
                p=run/'external_evaluation'/stage;p.mkdir(parents=True)
                (p/'evaluation.json').write_text(json.dumps({'result':{'correct':score,'n':100},'grader':'evaluator.rules_v0'}))
            data=load_run(run)
            self.assertEqual([data['evaluation'][s]['result']['correct'] for s in ('no_skill','parent','candidate')],[60,66,69])
            self.assertEqual(list_runs(root),['round-2-test'])
            (run/'external_evaluation/candidate/evaluation.json').unlink()
            self.assertEqual(load_run(run)['evaluation']['candidate']['status'],'incomplete')
    def test_corrupt_record_reports_error_without_zero_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'manifest.json').write_text('{')
            d=load_run(root)
            self.assertTrue(d['warnings']);self.assertFalse(d['evaluation'])
    def test_source_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'manifest.json').symlink_to(root/'elsewhere')
            self.assertTrue(load_run(root)['warnings'])
    def test_bad_diagnosis_is_skipped_with_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'diagnostics').mkdir()
            (root/'diagnostics/bad.json').write_text(json.dumps({'metric':'quality_impact','scores':None}))
            data=load_run(root)
            self.assertEqual(data['diagnostics'],[]);self.assertTrue(data['warnings'])
    def test_failed_evaluation_remains_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'external_evaluation/no_skill';folder.mkdir(parents=True)
            (folder/'failure.json').write_text(json.dumps({'error':'API unavailable'}))
            data=load_run(root)
            self.assertEqual(data['evaluation']['no_skill']['status'],'failed');self.assertTrue(data['warnings'])
    def test_plain_evaluator_cli_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'external_evaluation/no_skill';folder.mkdir(parents=True)
            (folder/'evaluation.json').write_text(json.dumps({'correct':71,'n':100,'score':.71}))
            self.assertEqual(load_run(root)['evaluation']['no_skill']['result']['correct'],71)
