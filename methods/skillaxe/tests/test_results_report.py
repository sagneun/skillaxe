import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import results


class ResultsReportTests(unittest.TestCase):
    def test_reports_rejected_candidate_and_only_matching_single_test_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);run=root/'round-8-fixture';run.mkdir()
            def save(path,value):
                path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))
            save(run/'candidate.json',{'content_hash':'candidate-hash'})
            save(run/'manifest.json',{'task_ids':['q1','q2']})
            for stage,correct in [('parent',71),('candidate',70),('no_skill',71)]:
                save(run/f'external_evaluation/{stage}/evaluation.json',{'skill_hash':None if stage=='no_skill' else ('candidate-hash' if stage=='candidate' else 'parent-hash'),'result':{'correct':correct,'n':100}})
            save(run/'evaluation_followup.json',{'mode':'evaluation_only','status':'complete'})
            test={'status':'complete','skill_hash':'candidate-hash','source_skill':str(run/'candidate.json'),'selected_run':{'correct':141,'n':200},'additional_completed_runs':2}
            save(root/'test-a/single_run_result.json',test)
            save(root/'test-z/single_run_result.json',{**test,'skill_hash':'other','selected_run':{'correct':199,'n':200}})
            row={'round':8,'week':4,'skillaxe':{'output':str(run)},'full':{'before':71,'after':None,'n':100},'accepted':False,'rejected_by':'guard','reason':'unknown diagnosis reference','llm_calls':92,'seconds':211.8,'ruler':'skipped','week_correction':{'from':0,'to':4}}
            log=root/'rounds.jsonl';log.write_text(json.dumps(row)+'\n')
            out=io.StringIO()
            with patch('sys.argv',['results','--week','4','--log',str(log)]),contextlib.redirect_stdout(out):results.main()
            text=out.getvalue()
            self.assertIn('L1 70/100',text)
            self.assertIn('활성 스킬: 71/100',text)
            self.assertIn('141/200',text);self.assertNotIn('199/200',text)
            self.assertIn('92회',text);self.assertIn('211.8초',text)
            self.assertIn('보완 평가',text);self.assertIn('week 0 → 4',text)

    def test_missing_log_is_reported_without_traceback(self):
        with patch('sys.argv',['results','--week','4','--log','/nonexistent/rounds.jsonl']),contextlib.redirect_stdout(io.StringIO()) as output:
            results.main()
        self.assertIn('no rounds',output.getvalue())
