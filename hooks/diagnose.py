"""틀린 문제를 보고 원인 한 줄을 어떻게 만들지. 기본: 틀린 문제 표본을 Improver LLM에 주고 diagnose.md 로 한 줄."""
from __future__ import annotations
import random
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4
import json
from llm.providers import Client
from sql_agent.schema import schema_text
from sql_agent.run import run_with_skill
from methods.skillaxe.contracts import TaskInput, ExecutionPolicy
from methods.skillaxe.skills import load_skill
from methods.skillaxe.embeddings import SentenceEmbeddings
from methods.skillaxe.diagnostics.trigger import TriggerParser, diagnose_trigger
from methods.skillaxe.diagnostics.suite import diagnose_all
from methods.skillaxe.brief import build_brief
from methods.skillaxe.records import write_json
from loop.context import RoundContext
from hooks.build_prompt import target_wrong

KNOBS = {
    "diagnose_n": ("int", 5, 25, 15),     # 진단에 보여 줄 틀린 문제 수
    "diagnose_focus": ("str", 300, ""),   # 진단할 때 무엇을 먼저 보라는 한 문장
}
KNOB_DOCS = {
    "diagnose_n": "how many wrong examples the diagnosis step reads before writing its one-sentence cause",
    "diagnose_focus": "an instruction sentence telling the diagnosis step which kind of failure to look at first",
}


def diagnose(ctx: RoundContext) -> str:
    if ctx.config.get("target_kind") == "skill":
        return diagnose_round(ctx)
    k = lambda name: (ctx.improver or {}).get(name, KNOBS[name][-1])
    wrong = target_wrong(ctx)   # build_prompt의 target_error_class와 같은 유형을 진단한다
    if not wrong:
        return "no wrong answers"
    random.Random(ctx.seed).shuffle(wrong)
    wrong = wrong[: k("diagnose_n")]
    user = "\n".join(f"Q: {ctx.problem(p['id'])['question']}\nSQL: {ctx.prediction(p['id'])}\nerror: {p['error']}" for p in wrong)
    system = ctx.prompt_text("diagnose.md") + (f"\nFocus: {k('diagnose_focus')}" if k("diagnose_focus") else "")
    return ctx.llm([{"role": "system", "content": system}, {"role": "user", "content": user}],
                   role="improver", max_tokens=ctx.config.get("improver_max_tokens", 4096)).strip()


def diagnose_round(ctx):
    """문제 선택은 사전 ID만 사용. ctx.before/predictions/recent_log를 읽지 않는다."""
    options=ctx.config['skillaxe']
    if '_skillaxe_round_output' in ctx.config:
        root=Path(ctx.config['_skillaxe_round_output'])
    else:
        root=Path(options.get('output_dir','logs/skillaxe'))/f'round-{ctx.round}-{uuid4().hex[:8]}'
        root.mkdir(parents=True,exist_ok=False)
    ctx.skillaxe_output=root
    skill=load_skill(Path(ctx.config['skill_path']))
    state={'status':'running','round':ctx.round,'skill_hash':skill.content_hash,'task_ids':options['task_ids'],
           'config':options,'parent':ctx.parent,'mode':'live','implemented_metrics':
           ['quality_impact','trigger_precision','instruction_compliance','solution_path_coverage']}
    write_json(root/'manifest.json',state)
    reports=[]
    try:
        # 설정·모델 로딩에 실패하면 Refiner를 호출하지 않는다.
        embeddings=SentenceEmbeddings(options['embedding_model'],options['embedding_revision'],
                                      options.get('embedding_cache','logs/skillaxe/embedding-cache'))
        parser=TriggerParser(options['parser_model'],options['parser_version'])
        agent=Client(role='agent',max_tokens=options.get('agent_max_tokens',512),independent=True)
        judge=Client(role='improver',max_tokens=options.get('judge_max_tokens',4096),independent=True,
                     single_request=options.get('judge_json_mode',False))
        state.update(embedding=embeddings.settings,parser=parser.settings,
                     agent=asdict(agent.settings),judge=asdict(judge.settings))
        write_json(root/'skills'/'current.json',{**asdict(skill),'content_hash':skill.content_hash})
        trigger=diagnose_trigger(skill,embeddings,parser,options.get('alpha',.5))
        write_json(root/'diagnostics'/'trigger.json',trigger)
        for index,task_id in enumerate(options['task_ids']):
            raw=ctx.problem(task_id)
            task=TaskInput(task_id,raw['question'],raw['db_id'],schema_text(ctx.config['tables'],raw['db_id']))
            write_json(root/'inputs'/f'{index}.json',asdict(task))
            database=Path(ctx.config['db_dir'])/task.db_id/f'{task.db_id}.sqlite'
            policy=ExecutionPolicy(timeout_seconds=float(ctx.config.get('sql_timeout_sec',5)))
            traces=[run_with_skill(task,s,database,agent,policy) for s in (None,skill)]
            for trace in traces:
                write_json(root/'traces'/f'{trace.trace_id}.json',asdict(trace))
                ctx.llm_calls+=len(trace.agent_calls)
            report=diagnose_all(task,skill,*traces,judge,embeddings,parser,seed=ctx.seed,config=options,trigger=trigger)
            reports.append(report)
            for name,d in report['axes'].items():
                if name!='trigger_precision':
                    ctx.llm_calls+=len(d['calls'])
                    write_json(root/'diagnostics'/f'{index}-{name}.json',d)
        brief=build_brief(reports)
        ctx.skillaxe_brief=brief
        write_json(root/'brief.json',brief)
        state['status']='complete' if brief['ready'] else 'diagnosis_unavailable'
    except Exception as exc:
        state.update(status='diagnosis_unavailable',error_type=type(exc).__name__)
        ctx.skillaxe_brief={'brief_id':str(uuid4()),'ready':False,'diagnoses':[],
                            'instructions':['Diagnosis failed; inspect local model/parser setup and recorded artifacts.']}
        write_json(root/'brief.json',ctx.skillaxe_brief,replace=True)
    write_json(root/'manifest.json',state,replace=True)
    return json.dumps({'status':state['status'],'brief_id':ctx.skillaxe_brief['brief_id'],'output':str(root)})
