import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from methods.skillaxe.contracts import SkillVersion
from methods.skillaxe.skills import document_content
from loop.patch import Patch

class LoopIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'active.json'
        self.skill=SkillVersion('count','L0','Count rows','Use COUNT(*)')
        self.path.write_text(json.dumps(asdict(self.skill)))
        self.brief={'ready':True,'diagnoses':[{'diagnosis_id':'d1','evidence':{}}]}
        self.ctx=SimpleNamespace(config={'target_kind':'skill','skill_path':str(self.path)},
            block_name='skill',block=self.path.read_text(),blocks={'skill':self.path.read_text()},skillaxe_brief=self.brief)
        self.archive=Mock(); self.archive.seen.return_value=False

    def candidate(self,body):
        value={**document_content(self.skill),'body':body,'changes':[{'diagnosis_ids':['d1'],'rule_ids':[],'reason':'clarify'}]}
        return Patch('skill',json.dumps(value),'clarify')

    def test_skill_precheck_accepts_json_instead_of_python(self):
        from loop.run import precheck
        result,why=precheck(self.ctx,self.candidate('Use COUNT(*) for all rows.'),['skill'],self.archive)
        self.assertIsNotNone(result,why)

    def test_no_change_is_not_retried(self):
        from loop.run import propose_valid
        self.ctx.llm_calls=0
        with patch('loop.run.build_prompt',return_value=[]), patch('loop.run.propose',return_value=[self.candidate(self.skill.body)]) as propose:
            result,reasons,attempts,calls=propose_valid(self.ctx,['skill'],self.archive)
        self.assertIsNone(result)
        self.assertIn('no_change',reasons)
        self.assertEqual(propose.call_count,1)

    def test_unavailable_diagnostic_never_calls_refiner(self):
        from loop.run import propose_valid
        self.ctx.skillaxe_brief['ready']=False; self.ctx.llm_calls=0
        with patch('loop.run.build_prompt') as build:
            result,reasons,*_=propose_valid(self.ctx,['skill'],self.archive)
        self.assertIsNone(result); build.assert_not_called()
        self.assertIn('diagnosis_unavailable',reasons)

    def test_refiner_input_has_no_grading_or_history(self):
        from hooks.build_prompt import refiner_messages
        self.ctx.before={'correct':99,'per_problem':[{'error':'SECRET_MISMATCH'}]}
        self.ctx.recent_log=[{'secret':'SECRET_HISTORY'}]
        messages=refiner_messages(self.ctx)
        self.assertNotIn('SECRET',json.dumps(messages))

if __name__=='__main__': unittest.main()

class EvaluationBridgeTests(unittest.TestCase):
    def test_eval_preserves_artifacts_and_passes_same_limits(self):
        from loop import run
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'logs').mkdir()
            active=root/'active.json'; active.write_text(json.dumps(asdict(SkillVersion('count','L0','Count','Use COUNT(*)'))))
            cfg={'target_kind':'skill','skill_path':str(active),'_skillaxe_round_output':str(root/'round'),
                 'agent_timeout_sec':10,'tables':'tables.json','db_dir':'database','sql_timeout_sec':.25,
                 'skillaxe':{'agent_max_tokens':777}}
            def agent(problems,out,timeout,**kwargs):
                self.assertEqual(kwargs['max_tokens'],777)
                self.assertEqual(kwargs['sql_timeout'],.25)
                self.assertEqual(kwargs['skill'],str(active))
                out.write_text('{"id":"q1","sql":"SELECT 1"}\n')
                kwargs['trace_out'].write_text('{"trace_id":"trace1"}\n')
            with patch.object(run,'ROOT',root),patch.object(run,'run_agent',side_effect=agent), \
                 patch.object(run,'evaluate',return_value={'n':1,'correct':1,'per_problem':[]}):
                for stage in ('parent','candidate'):
                    run.eval_on([{'id':'q1','question':'Q','db_id':'db','gold_sql':'secret'}],cfg,stage)
            for stage in ('parent','candidate'):
                folder=root/'round'/'external_evaluation'/stage
                self.assertTrue((folder/'predictions.jsonl').exists())
                self.assertTrue((folder/'traces.jsonl').exists())
                self.assertEqual(json.loads((folder/'evaluation.json').read_text())['result']['correct'],1)
                self.assertNotIn('secret',(folder/'evaluation.json').read_text())
            self.assertFalse((root/'logs'/'_problems_parent.json').exists())

    def test_refiner_failure_keeps_request_and_error_type(self):
        from hooks.propose import propose_skill
        with tempfile.TemporaryDirectory() as d:
            ctx=SimpleNamespace(skillaxe_output=Path(d),config={},llm=Mock(side_effect=RuntimeError('SECRET_KEY')))
            with self.assertRaises(RuntimeError):propose_skill(ctx,[{'role':'user','content':'safe input'}])
            saved=json.loads(next((Path(d)/'refiner').glob('*.json')).read_text())
            self.assertEqual(saved['status'],'failed')
            self.assertEqual(saved['error_type'],'RuntimeError')
            self.assertNotIn('SECRET_KEY',json.dumps(saved))

class GradingFailureTests(unittest.TestCase):
    def test_grading_failure_is_recorded_without_leaving_gold_input(self):
        from loop import run
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'logs').mkdir()
            cfg={'target_kind':'skill','skill_path':'unused','_skillaxe_round_output':str(root/'round'),
                 'agent_timeout_sec':1,'tables':'unused','db_dir':'unused','sql_timeout_sec':1,'skillaxe':{}}
            def agent(problems,out,*args,**kwargs):out.write_text('{"id":"q","sql":"SELECT 1"}\n')
            with patch.object(run,'ROOT',root),patch.object(run,'run_agent',side_effect=agent), \
                 patch.object(run,'evaluate',side_effect=RuntimeError('SECRET')):
                result,error,predictions=run.eval_on([{'id':'q','gold_sql':'SECRET'}],cfg,'candidate')
            self.assertIsNone(result);self.assertIn('RuntimeError',error)
            saved=(root/'round'/'external_evaluation'/'candidate'/'failure.json').read_text()
            self.assertNotIn('SECRET',saved)
            self.assertFalse((root/'logs'/'_problems_candidate.json').exists())
