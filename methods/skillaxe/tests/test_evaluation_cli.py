import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch
from methods.skillaxe.contracts import SkillVersion
from methods.skillaxe.skills import document_content
from methods.skillaxe import evaluate_skill as cli


class EvaluationCLITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.run=self.root/'round-1-fixture';self.run.mkdir()
        self.skill=SkillVersion('s','L0','description','Use schema columns')
        self.save(self.run/'skills/current.json',asdict(self.skill))
        self.save(self.run/'brief.json',{'diagnoses':[]})
        self.cfg={'week':4,'log':str(self.root/'rounds.jsonl'),'validation':str(self.root/'validation.json'),
                  'agent_timeout_sec':10,'tables':'tables','db_dir':'db','sql_timeout_sec':5,'skillaxe':{'agent_max_tokens':512}}
        self.save(self.root/'validation.json',[{'id':'q','db_id':'db','question':'Q','gold_sql':'SECRET'}])
        (self.root/'rounds.jsonl').write_text(json.dumps({'week':4,'skillaxe':{'output':str(self.run)}})+'\n')

    def save(self,path,value):
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))

    def test_latest_run_requires_matching_week_and_existing_records(self):
        self.assertEqual(cli.resolve_run(self.cfg,None),self.run)
        with self.assertRaisesRegex(ValueError,'실행 기록'):cli.resolve_run({**self.cfg,'week':5},None)

    def test_recovery_is_explicit_and_keeps_document_and_validation_error(self):
        content={**document_content(self.skill),'body':'Use qualified columns','changes':[{'diagnosis_ids':['unknown'],'rule_ids':[],'reason':'clarify'}]}
        self.save(self.run/'refiner/response.json',{'status':'success','messages':[{},{}],'response':json.dumps(content)})
        with self.assertRaisesRegex(ValueError,'recover'):cli.prepare_candidate(self.run,False)
        candidate=cli.prepare_candidate(self.run,True)
        self.assertEqual(json.loads(candidate.read_text())['body'],content['body'])
        self.assertEqual(json.loads((self.run/'evaluation_followup.json').read_text())['reference_validation_error'],'unknown diagnosis reference')

    def test_validation_uses_existing_agent_and_grader_then_reuses_completed_result(self):
        self.save(self.run/'candidate.json',asdict(SkillVersion('s','L1','desc','body')))
        def agent(problems,out,*args,**kwargs):
            self.assertEqual(kwargs['max_tokens'],512)
            self.assertEqual(Path(kwargs['skill']).name,'skill.json')
            out.write_text('{"id":"q","sql":"SELECT 1"}\n')
            return None
        result={'correct':1,'n':1,'score':1.,'per_problem':[{'id':'q','correct':True}]}
        with patch.object(cli,'run_agent',side_effect=agent) as run,patch.object(cli,'evaluate',return_value=result):
            a=cli.evaluate_once(self.cfg,self.run,'validation','candidate',False)
            b=cli.evaluate_once(self.cfg,self.run,'validation','candidate',False)
        self.assertEqual(a['result']['correct'],1);self.assertEqual(a,b);self.assertEqual(run.call_count,1)

    def test_test_saves_only_aggregate_and_never_uses_test_for_refinement(self):
        self.save(self.run/'candidate.json',asdict(SkillVersion('s','L1','desc','body')))
        heldout=self.root/'heldout-fixture.json';self.save(heldout,[{'id':'q','db_id':'db','question':'Q','gold_sql':'SECRET'}])
        def agent(problems,out,*args,**kwargs):out.write_text('{"id":"q","sql":"SELECT 1"}\n')
        with patch.object(cli,'TEST_DATA',heldout),patch.object(cli,'run_agent',side_effect=agent),patch.object(cli,'evaluate',return_value={'n':1,'correct':1,'score':1.,'per_problem':[{'secret':'SECRET'}]}):
            record=cli.evaluate_once(self.cfg,self.run,'test','candidate',False)
        self.assertEqual(record['selected_run']['correct'],1)
        self.assertNotIn('SECRET',json.dumps(record));self.assertEqual(record['requested_runs'],1)
        self.assertFalse(record['automatic_adoption'])
