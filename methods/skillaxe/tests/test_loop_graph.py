"""기존 loop graph로 네 진단→후보→고정 kernel→복원을 검증한다. 합성 데이터만 사용."""
import json
import os
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from methods.skillaxe.contracts import SkillVersion
from methods.skillaxe.tests import test_execution as fixtures
from methods.skillaxe.tests.test_diagnostic_flow import Embeddings, Parser

class MemoryArchive:
    def __init__(self,path):
        self.path=path; self.versions={'parent0':path.read_text()}; self.scores={}; self.best=None
        self.repo=SimpleNamespace(commit=lambda ref:SimpleNamespace(hexsha=ref))
    def head(self): return 'parent0'
    def checkout(self,sha,paths): self.path.write_text(self.versions[sha])
    def record(self,sha,score,parent):
        if score is not None:self.scores[sha]=score
    def set_best(self,sha):
        if self.best is None or self.scores[sha]>self.scores[self.best]: self.best=sha; return True
        return False
    def commit(self,message,paths): self.versions['cand001']=self.path.read_text(); return 'cand001'
    def promote(self,*args): pass
    def seen(self,h): return False
    def add_seen(self,h): pass

class GraphTests(unittest.TestCase):
    def test_four_axes_candidate_uses_existing_kernel_and_reverts_when_rejected(self):
        from loop import run
        for accepted in (True,False):
            with self.subTest(accepted=accepted), tempfile.TemporaryDirectory() as d:
                root=Path(d); (root/'logs').mkdir()
                # Small independent SQLite fixture, unrelated to official validation/test.
                import sqlite3
                dbdir=root/'database'/'sample'; dbdir.mkdir(parents=True)
                with sqlite3.connect(dbdir/'sample.sqlite') as db:
                    db.execute('CREATE TABLE items (name TEXT)'); db.execute("INSERT INTO items VALUES ('a')")
                active=root/'active.json'; active.write_text(json.dumps(asdict(SkillVersion('count','L0','Count rows','Use COUNT(*)'))))
                validation=root/'validation-fixture.json'; validation.write_text(json.dumps([{'id':'q1','db_id':'sample','question':'How many rows?','gold_sql':'SECRET_GOLD'}]))
                cfg=dict(validation=str(validation),tables='unused',db_dir=str(root/'database'),screen_size=1,screen_drop=2,
                    log=str(root/'logs'/'rounds.jsonl'),evolve_files=[str(active)],editable_blocks=['skill'],target_kind='skill',skill_path=str(active),
                    week=0,agent_timeout_sec=10,sql_timeout_sec=5,improver_max_tokens=4096,
                    skillaxe=dict(task_ids=['q1'],output_dir=str(root/'records'),embedding_model='fixture',embedding_revision='fixture',parser_model='fixture',parser_version='fixture'))
                archive=MemoryArchive(active)
                judge=fixtures.SequenceClient(
                    json.dumps(dict(preference='tie',evidence='Same SQL.',uncertainty=False,uncertainty_reason='')),
                    json.dumps({'rules':[dict(rule_id='r1',rule='Count',severity=3,source_quote='Use COUNT(*)')]}),
                    json.dumps({'judgments':[dict(rule_id='r1',relevant=True,a=1.,g=1.,f=0.,evidence='COUNT(*) observed',insufficient_evidence=False)]}),
                    json.dumps({'paths':['COUNT aggregation','Scalar subquery','Non-null key count']}))
                agent=fixtures.SequenceClient('SELECT COUNT(*) FROM items','SELECT COUNT(*) FROM items')
                refiner_inputs=[]
                def refine(messages,**kwargs):
                    refiner_inputs.append(messages)
                    payload=json.loads(messages[-1]['content']); value=payload['current_skill']; value['body']='Use COUNT(*) for all rows.'
                    value['changes']=[dict(diagnosis_ids=[payload['brief']['diagnoses'][0]['diagnosis_id']],rule_ids=[],reason='Clarify scope')]
                    return json.dumps(value)
                def evaluation(problems,config,tag):
                    modified=json.loads(active.read_text())['version']!='L0'
                    correct=modified and accepted
                    return {'n':1,'correct':int(correct),'per_problem':[{'id':'q1','correct':correct,'error':None if correct else 'result mismatch'}]},None,{'q1':'new' if modified else 'old'}
                original_kernel=run.K.kernel_accept
                with patch.dict(os.environ,{},clear=False), patch.object(run,'ROOT',root), \
                     patch.object(run.K,'anchors_sha',return_value='fixed'), patch.object(run.K,'read_improver',return_value={}), \
                     patch.object(run,'eval_on',side_effect=evaluation), patch.object(run.llm,'chat',side_effect=refine), \
                     patch('hooks.diagnose.SentenceEmbeddings',return_value=Embeddings()), \
                     patch('hooks.diagnose.TriggerParser',return_value=Parser()), \
                     patch('hooks.diagnose.Client',side_effect=lambda role,**kw:agent if role=='agent' else judge), \
                     patch('hooks.diagnose.schema_text',return_value='table items: name text'), \
                     patch.object(run.K,'kernel_accept',wraps=original_kernel) as kernel:
                    graph=run.build_graph(cfg,archive,1); graph.invoke({'rnd':1})
                self.assertEqual(kernel.call_count,1)
                entry=json.loads(Path(cfg['log']).read_text())
                self.assertEqual(entry['accepted'],accepted)
                version=json.loads(active.read_text())['version']
                self.assertEqual(version,'L1' if accepted else 'L0')
                output=Path(entry['skillaxe']['output'])
                self.assertTrue((output/'candidate.json').exists())
                self.assertEqual(len(json.loads((output/'brief.json').read_text())['diagnoses']),4)
                self.assertNotIn('SECRET_GOLD',json.dumps(refiner_inputs))
                self.assertNotIn('mismatch',json.dumps(refiner_inputs))

if __name__=='__main__':unittest.main()
