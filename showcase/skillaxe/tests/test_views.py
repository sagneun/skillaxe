import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dashboard.views import score, outcome, diagnostic_view

class ViewTests(unittest.TestCase):
    def test_missing_and_zero_scores_differ(self):
        d={'evaluation':{'parent':{'result':{'correct':0,'n':100}}}}
        self.assertEqual(score(d,'no_skill'),'미실행')
        self.assertEqual(score(d,'parent'),'0 / 100')
    def test_rejected_candidate_not_presented_as_adopted(self):
        d={'skills':{'candidate':{'version':'L1'}},'evaluation':{'parent':{'result':{'correct':66,'n':100}},'candidate':{'result':{'correct':69,'n':100}}},'round_summary':{'accepted':False}}
        self.assertIn('+3',outcome(d));self.assertIn('초기 스킬을 유지',outcome(d))
    def test_missing_diagnosis_not_fabricated(self):
        self.assertIn('기록이 없습니다',diagnostic_view({'diagnostics':[]},'quality_impact','q'))
    def test_failure_is_not_unexecuted(self):
        self.assertEqual(score({'evaluation':{'no_skill':{'status':'failed'}}},'no_skill'),'실패')
        self.assertEqual(score({'evaluation':{'no_skill':{'status':'incomplete'}}},'no_skill'),'평가 미완료')
