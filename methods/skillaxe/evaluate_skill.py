"""저장된 스킬의 명시적 보완 평가. 기존 SQL 실행·채점기를 재사용하며 채택하지 않는다."""
from __future__ import annotations
import argparse
import json
from dataclasses import asdict
from pathlib import Path
from time import monotonic
import yaml
from loop import kernel as K
from loop.env import require_llm
from loop.run import run_agent
from evaluator.evaluate import evaluate
from llm.providers import Client
from .skills import load_skill, candidate_skill, validate_candidate

TEST_DATA = Path('data/test.json')


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2))


def resolve_run(config, supplied):
    if supplied:
        run=Path(supplied)
        if not (run/'manifest.json').exists():
            raise ValueError('RUN은 manifest.json이 있는 round 폴더여야 합니다')
        return run
    log=Path(config['log'])
    rows=[json.loads(line) for line in log.read_text().splitlines() if line.strip()] if log.exists() else []
    rows=[r for r in rows if r['week']==config['week'] and r.get('skillaxe',{}).get('output')]
    if not rows:
        raise ValueError('해당 주차 실행 기록이 없습니다. 먼저 make skillaxe-round를 실행하세요')
    run=Path(rows[-1]['skillaxe']['output'])
    if not run.is_dir(): raise ValueError('실행 기록 폴더가 없습니다')
    return run


def prepare_candidate(run, recover):
    target=run/'candidate.json'
    if target.exists():
        load_skill(target)
        return target
    if not recover:
        raise ValueError('후보가 없습니다. 참조 오류로 거절된 문서를 평가하려면 --recover-candidate (RECOVER=1)를 명시하세요')
    records=[]
    for file in (run/'refiner').glob('*.json'):
        record=json.loads(file.read_text())
        if record.get('status')=='success' and record.get('response'):
            records.append((len(record['messages']),file.stat().st_mtime,file,record))
    if not records: raise ValueError('복원할 Improver 응답이 없습니다. 진단 실패 또는 무변경 여부를 확인하세요')
    _,_,source,record=max(records,key=lambda r:(r[0],r[1]))
    current=load_skill(run/'skills/current.json')
    candidate=candidate_skill(record['response'],current)  # 문서 형식 오류는 우회하지 않는다.
    brief=json.loads((run/'brief.json').read_text())
    error=None
    try: validate_candidate(record['response'],current,brief)
    except ValueError as exc: error=str(exc)
    save(target,{**asdict(candidate),'content_hash':candidate.content_hash})
    save(run/'evaluation_followup.json',dict(status='prepared',mode='evaluation_only',
        source_response=str(source),reference_validation_error=error,automatic_adoption=False,
        note='Saved Improver document unchanged; original round rejection retained.'))
    return target


def evaluate_once(config, run, split, condition, recover=False):
    if split=='test' and condition!='candidate':
        raise ValueError('test 명령은 고정 후보만 평가합니다')
    source=prepare_candidate(run,recover) if condition=='candidate' else None
    skill=load_skill(source) if source else None
    skill_hash=skill.content_hash if skill else None
    if split=='test':
        for old_path in sorted(run.parent.glob('test-*/single_run_result.json'),reverse=True):
            old=json.loads(old_path.read_text())
            if (old.get('status')=='complete' and old.get('skill_hash')==skill_hash
                    and Path(old.get('source_skill','')).resolve()==source.resolve()):
                return old  # 기존 수동 1회 평가 기록도 재사용한다.
    folder=(run/'test') if split=='test' else (run/'external_evaluation'/condition)
    result_path=folder/('single_run_result.json' if split=='test' else 'evaluation.json')
    if result_path.exists():
        old=json.loads(result_path.read_text())
        if old.get('skill_hash')!=skill_hash: raise ValueError('기존 평가와 스킬 해시가 다릅니다')
        if split=='test' and old.get('status')!='complete': raise ValueError('기존 test 평가가 미완료 상태입니다')
        return old
    if folder.exists(): raise ValueError('미완료 평가 폴더가 있습니다. 기록을 확인하세요: '+str(folder))
    folder.mkdir(parents=True)
    snapshot=folder/'skill.json' if source else None
    if snapshot: snapshot.write_bytes(source.read_bytes())
    input_path=TEST_DATA if split=='test' else Path(config['validation'])
    started=monotonic()
    try:
        # 채점 프로세스만 원본을 읽는다. run_agent가 질문·DB·ID만 agent에 전달한다.
        problems=json.loads(input_path.read_text())
        out=folder/'predictions.jsonl'
        error=run_agent(problems,out,config['agent_timeout_sec'],skill=snapshot,
            trace_out=folder/'traces.jsonl' if split=='validation' else None,
            tables=config['tables'],db_dir=config['db_dir'],
            max_tokens=config['skillaxe'].get('agent_max_tokens',512),sql_timeout=float(config['sql_timeout_sec']))
        if error: raise RuntimeError('SQL agent 실행 실패')
        result=evaluate(str(out),str(input_path),config['db_dir'],config['sql_timeout_sec'])
        if snapshot and load_skill(snapshot).content_hash!=skill_hash: raise ValueError('평가 중 스킬이 변경됐습니다')
        common=dict(skill_hash=skill_hash,grader='evaluator.rules_v0',
            model=config.get('_agent_settings',{}),seconds=round(monotonic()-started,1),
            ruler=getattr(K,'RULER_STATUS','unchecked'),automatic_adoption=False)
        if split=='test':
            # test 정오답·예측은 보고서와 진단에 전달하지 않는다.
            record=dict(**common,status='complete',requested_runs=1,source_skill=str(source),
                selected_run={'run':1,'correct':result['correct'],'n':result['n'],'score':result['score']})
        else: record=dict(**common,result=result)
        save(result_path,record)
        followup=run/'evaluation_followup.json'
        if split=='validation' and condition=='candidate':
            details=json.loads(followup.read_text()) if followup.exists() else {'mode':'evaluation_only','automatic_adoption':False}
            details.update(status='complete',after=result['correct'],n=result['n'],seconds=record['seconds'])
            save(followup,details)
        return record
    except Exception as exc:
        save(folder/'failure.json',{'status':'failed','error_type':type(exc).__name__})
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',default='methods/skillaxe/configs/loop.yaml')
    parser.add_argument('--run',help='생략하면 설정한 주차의 최신 round')
    parser.add_argument('--split',choices=['validation','test'],default='validation')
    parser.add_argument('--condition',choices=['candidate','no_skill'],default='candidate')
    parser.add_argument('--recover-candidate',action='store_true')
    args=parser.parse_args()
    try:
        config=yaml.safe_load(Path(args.config).read_text())
        run=resolve_run(config,args.run)
        require_llm();K.require_ruler()
        config['_agent_settings']=asdict(Client(role='agent',max_tokens=config['skillaxe'].get('agent_max_tokens',512),independent=True).settings)
        result=evaluate_once(config,run,args.split,args.condition,args.recover_candidate)
        score=result['selected_run'] if args.split=='test' else result['result']
        print(f"{args.split} {args.condition}: {score['correct']}/{score['n']} ({100*score['correct']/score['n']:.1f}%)")
        print(f"기록: {run}; 자동 채택하지 않음")
    except (ValueError,RuntimeError,FileNotFoundError,json.JSONDecodeError) as exc:
        parser.exit(1,str(exc)+'\n')


if __name__=='__main__': main()
