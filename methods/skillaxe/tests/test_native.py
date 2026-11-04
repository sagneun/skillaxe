import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch
from methods.skillaxe.tests import test_execution as fixtures
SequenceClient = fixtures.SequenceClient
from methods.skillaxe.contracts import SkillVersion

class NativeTests(unittest.TestCase):
    def setUp(self): fixtures.ExecutionTests.setUp(self)

    def test_cli_writes_legacy_predictions_and_skill_evidence(self):
        from sql_agent import run
        root=Path(self.tmp.name)
        task=root/'tasks.json'; output=root/'out.jsonl'; traces=root/'traces.jsonl'; skill=root/'skill.json'
        task.write_text(json.dumps([{'id':'q1','question':self.task.question,'db_id':'sample'}]))
        skill.write_text(json.dumps(asdict(SkillVersion('count','L0','Count','Use COUNT(*)'))))
        client=SequenceClient('SELECT COUNT(*) FROM items')
        from sql_agent.run import execute_sql as real_execute_sql
        with patch('sql_agent.run.schema_text',return_value=self.task.schema), \
             patch('sql_agent.run.DATA_DIR',root), patch('llm.providers.Client',return_value=client), \
             patch('sql_agent.run.database_hash',return_value='db'), \
             patch('sql_agent.run.execute_sql') as execute:
            execute.return_value=real_execute_sql(self.database,'SELECT COUNT(*) FROM items',__import__('methods.skillaxe.contracts',fromlist=['ExecutionPolicy']).ExecutionPolicy())
            run.main(['--problems',str(task),'--out',str(output),'--skill',str(skill),'--trace-out',str(traces)])
        self.assertEqual(json.loads(output.read_text()),{'id':'q1','sql':'SELECT COUNT(*) FROM items'})
        trace=json.loads(traces.read_text())
        self.assertEqual(trace['execution']['rows'],[[3]])
        self.assertIn('Use COUNT(*)',str(trace['agent_calls']))

if __name__=='__main__': unittest.main()

class PolicyRegressionTests(unittest.TestCase):
    def setUp(self): fixtures.ExecutionTests.setUp(self)
    def test_requested_policy_survives_native_observer(self):
        from sql_agent.run import run_with_skill as run_agent
        from methods.skillaxe.contracts import ExecutionPolicy
        policy=ExecutionPolicy(row_limit=1,timeout_seconds=.1)
        trace=run_agent(self.task,None,self.database,SequenceClient('SELECT * FROM items'),policy)
        self.assertEqual(trace.execution.policy,policy)
        self.assertEqual(len(trace.execution.rows),1)
