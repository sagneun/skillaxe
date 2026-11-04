import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from hooks.on_round_start import on_round_start
from methods.skillaxe.contracts import Trace, SkillVersion, ExecutionPolicy
from methods.skillaxe.tests import test_execution as fixtures
SequenceClient = fixtures.SequenceClient
from sql_agent.run import run_with_skill


class FailureSelectionTests(unittest.TestCase):
    def context(self, rows):
        return SimpleNamespace(config={'target_kind': 'skill', 'skillaxe': {'task_ids': [r['id'] for r in rows]}},
            before={'per_problem': rows}, problems={r['id']: {'db_id': r.get('db', 'db')} for r in rows},
            improver={}, seed=8, parent='parent')

    def test_selects_current_failures_not_first_five_correct_tasks(self):
        rows=[{'id': f'ok{i}', 'correct': True, 'error': None} for i in range(5)]
        rows += [{'id': f'bad{i}', 'correct': False, 'error': 'result mismatch'} for i in range(30)]
        ctx=self.context(rows);on_round_start(ctx)
        self.assertEqual(len(ctx.skillaxe_selection['task_ids']), 20)
        self.assertTrue(all(i.startswith('bad') for i in ctx.skillaxe_selection['task_ids']))
        other=self.context(rows);on_round_start(other)
        self.assertEqual(ctx.skillaxe_selection, other.skillaxe_selection)

    def test_fewer_than_twenty_failures_uses_only_available_failures(self):
        rows=[{'id':f'bad{i}','correct':False,'error':'result mismatch'} for i in range(8)]
        rows += [{'id':'ok','correct':True,'error':None}]
        ctx=self.context(rows);on_round_start(ctx)
        self.assertEqual(set(ctx.skillaxe_selection['task_ids']),{f'bad{i}' for i in range(8)})

    def test_spreads_sample_over_error_types_and_databases(self):
        rows=[{'id': f'e{i}', 'correct': False, 'error': 'OperationalError: no such column', 'db':'a'} for i in range(10)]
        rows += [{'id':'m1','correct':False,'error':'result mismatch','db':'b'},
                 {'id':'m2','correct':False,'error':'result mismatch','db':'c'},
                 {'id':'gold','correct':False,'error':'gold failed: SECRET','db':'d'}]
        ctx=self.context(rows);on_round_start(ctx)
        ids=ctx.skillaxe_selection['task_ids']
        self.assertIn('m1',ids);self.assertIn('m2',ids);self.assertNotIn('gold',ids)

    def test_no_failures_does_not_fill_with_correct_tasks_or_call_models(self):
        from hooks.diagnose import diagnose_round
        ctx=self.context([{'id':'ok','correct':True,'error':None}]);on_round_start(ctx)
        self.assertEqual(ctx.skillaxe_selection['task_ids'],[])
        with tempfile.TemporaryDirectory() as directory:
            ctx.config['_skillaxe_round_output']=directory
            path=Path(directory)/'active.json';path.write_text(json.dumps(asdict(SkillVersion('s','L0','desc','body'))))
            ctx.config['skill_path']=str(path);ctx.round=1
            with patch('hooks.diagnose.Client') as client:
                result=json.loads(diagnose_round(ctx))
            client.assert_not_called();self.assertEqual(result['status'],'no_failures')
            self.assertFalse(ctx.skillaxe_brief['ready'])


class FailureTraceTests(unittest.TestCase):
    def setUp(self): fixtures.ExecutionTests.setUp(self)

    def test_saved_failure_roundtrip_preserves_sql_and_nested_evidence(self):
        skill=SkillVersion('s','L0','desc','Use schema columns')
        trace=run_with_skill(self.task,skill,self.database,SequenceClient('SELECT missing FROM items'),ExecutionPolicy())
        saved=json.loads(json.dumps(asdict(trace)))
        restored=Trace.from_record({**saved,'gold_sql':'SECRET'})
        self.assertEqual(json.loads(json.dumps(asdict(restored))),saved)
        self.assertIn('missing',restored.execution.error)

    def test_diagnosis_reuses_parent_failure_without_regenerating_treated_sql(self):
        from hooks.diagnose import diagnose_round
        skill=SkillVersion('s','L0','desc','Use schema columns')
        treated=run_with_skill(self.task,skill,self.database,SequenceClient('SELECT missing FROM items'),ExecutionPolicy())
        baseline=run_with_skill(self.task,None,self.database,SequenceClient('SELECT COUNT(*) FROM items'),ExecutionPolicy())
        root=Path(self.tmp.name)/'round';parent=root/'external_evaluation/parent';parent.mkdir(parents=True)
        (parent/'traces.jsonl').write_text(json.dumps(asdict(treated))+'\n')
        active=root/'active.json';active.write_text(json.dumps(asdict(skill)))
        options=dict(task_ids=[self.task.task_id],embedding_model='fixture',embedding_revision='fixture',parser_model='fixture',parser_version='fixture')
        ctx=SimpleNamespace(config={'target_kind':'skill','skillaxe':options,'skill_path':str(active),'_skillaxe_round_output':str(root),'tables':'unused','db_dir':str(self.database.parent),'sql_timeout_sec':5},
            before={'per_problem':[{'id':self.task.task_id,'correct':False,'error':'result mismatch SECRET_GRADE'}]},
            problems={self.task.task_id:{'db_id':self.task.db_id}},improver={},seed=1,parent='parent',round=1,llm_calls=0,
            problem=lambda _: {'question':self.task.question,'db_id':self.task.db_id,'gold_sql':'SECRET_GOLD'})
        on_round_start(ctx)
        fake=SequenceClient();embedding=SimpleNamespace(settings={});parser=SimpleNamespace(settings={})
        def suite(task,current,no_skill,with_skill,*args,**kwargs):
            self.assertEqual(with_skill.trace_id,treated.trace_id)
            self.assertEqual(with_skill.sql,'SELECT missing FROM items')
            self.assertNotIn('SECRET',json.dumps(asdict(task)))
            return {'ready_for_refinement':True,'axes':{}}
        with patch('hooks.diagnose.Client',return_value=fake),patch('hooks.diagnose.SentenceEmbeddings',return_value=embedding),patch('hooks.diagnose.TriggerParser',return_value=parser),patch('hooks.diagnose.schema_text',return_value=self.task.schema),patch('hooks.diagnose.diagnose_trigger',return_value={}),patch('hooks.diagnose.run_with_skill',return_value=baseline) as run,patch('hooks.diagnose.diagnose_all',side_effect=suite):
            diagnose_round(ctx)
        self.assertEqual(run.call_count,1)
        self.assertIsNone(run.call_args.args[1])
        self.assertNotIn('SECRET',json.dumps(ctx.skillaxe_brief))
