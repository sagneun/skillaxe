import json
import unittest
from methods.skillaxe.tests import test_execution as fixtures
from sql_agent.run import run_with_skill as run_agent
from methods.skillaxe.contracts import SkillVersion,ExecutionPolicy
from methods.skillaxe.diagnostics.suite import diagnose_all
from methods.skillaxe.brief import build_brief

class Embeddings:
    settings={'model':'fixed-test-vectors','mode':'mock'}
    def embed(self,texts): return [[1.,0.] if i%2==0 else [0.,1.] for i,_ in enumerate(texts)]

class Parser:
    settings={'model':'test-parser','mode':'mock'}
    def extract(self,skill):
        return [dict(phrase_id='p1',text='row count',context='Count rows.',polarity='positive'),
                dict(phrase_id='p2',text='null count',context='Avoid null counts.',polarity='negative')]

class FlowTests(unittest.TestCase):
    def setUp(self):
        fixtures.ExecutionTests.setUp(self)
        self.skill=SkillVersion('count','L0','Count rows','Use COUNT(*)')
        agent=fixtures.SequenceClient('SELECT COUNT(*) FROM items','SELECT COUNT(*) FROM items')
        self.traces=[run_agent(self.task,s,self.database,agent,ExecutionPolicy()) for s in (None,self.skill)]

    def judge(self,invalid=False):
        return fixtures.SequenceClient(
            json.dumps(dict(preference='tie',evidence='Equal SQL.',uncertainty=False,uncertainty_reason='')),
            json.dumps({'rules':[dict(rule_id='r1',rule='Count rows',severity=3,source_quote='Use COUNT(*)')]}),
            json.dumps({'judgments':[dict(rule_id='r1',relevant=True,a=.3,g=1.,f=0.,evidence='fixture evidence',insufficient_evidence=False)]}),
            'invalid JSON' if invalid else json.dumps({'paths':['Aggregate COUNT(*)','Scalar subquery count','Count keys when nonnull']}))

    def test_all_four_axes_feed_brief_without_gold_or_call_payloads(self):
        judge=self.judge()
        report=diagnose_all(self.task,self.skill,*self.traces,judge,Embeddings(),Parser())
        self.assertTrue(report['ready_for_refinement'])
        self.assertEqual(len(report['axes']),4)
        brief=build_brief([report])
        self.assertTrue(brief['ready'])
        self.assertNotIn('SECRET',json.dumps(judge.requests))
        self.assertNotIn('calls',json.dumps(brief))
        self.assertEqual(report['axes']['instruction_compliance']['evidence']['preserve_rule_ids'],['r1'])
        # 규칙 추출에는 작업을, 경로 생성에는 스킬 본문을 숨긴다.
        extraction=json.loads(judge.requests[1][-1]['content'])
        self.assertEqual(set(extraction),{'skill','source_lines'})
        self.assertTrue(all(line in extraction['skill'] for line in extraction['source_lines'].values()))
        paths=json.loads(judge.requests[-1][-1]['content'])
        self.assertEqual(set(paths),{'question','schema','skill_type','path_count'})

    def test_required_failure_blocks_refinement_and_preserves_call(self):
        report=diagnose_all(self.task,self.skill,*self.traces,self.judge(True),Embeddings(),Parser())
        self.assertFalse(report['ready_for_refinement'])
        result=report['axes']['solution_path_coverage']
        self.assertEqual(result['status'],'unavailable')
        self.assertEqual(result['scores'],{})
        self.assertEqual(result['calls'][0]['response'],'invalid JSON')
        self.assertFalse(build_brief([report])['ready'])

if __name__=='__main__': unittest.main()
