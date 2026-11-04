"""Read actual local round artifacts. No export step or experiment imports."""
import json
import re
from pathlib import Path


def list_runs(root: Path) -> list[str]:
    return sorted((p.name for p in root.glob('round-*') if p.is_dir() and not p.is_symlink()),
                  key=lambda name: (int(re.search(r'round-(\d+)',name).group(1)) if re.search(r'round-(\d+)',name) else -1,name))


def load_run(path: Path) -> dict:
    path=Path(path)
    if not path.is_dir() or path.is_symlink(): raise ValueError('Invalid round directory')
    warnings=[]
    def read(file,default=None):
        if file.is_symlink():
            warnings.append(f'{file.name}: symlink는 읽지 않습니다.');return default
        if not file.exists(): return default
        try:
            value=json.loads(file.read_text())
            if not isinstance(value,dict): raise ValueError('expected object')
            return value
        except (ValueError,OSError):
            warnings.append(f'{file.name}: 기록을 읽을 수 없습니다.');return default
    def traces(file):
        if file.is_symlink(): warnings.append(f'{file.name}: symlink는 읽지 않습니다.');return []
        if not file.exists(): return []
        rows=[]
        try:
            for line in file.read_text().splitlines():
                row=json.loads(line)
                if not isinstance(row,dict): raise ValueError('expected trace')
                rows.append({k:v for k,v in row.items() if k not in ('agent_call','agent_calls')})
        except (ValueError,OSError): warnings.append(f'{file.name}: 일부 실행 기록을 읽을 수 없습니다.')
        return rows
    manifest=read(path/'manifest.json',{})
    data={'name':path.name,'manifest':manifest,'tasks':[],'skills':{},'diagnostics':[],
          'evaluation':{},'brief':read(path/'brief.json'),'revision':read(path/'revision.json'),'round_summary':None,'warnings':warnings}
    for p in sorted((path/'inputs').glob('*.json')):
        row=read(p)
        if row and isinstance(row.get('task_id'),str): data['tasks'].append(row)
    for label,p in [('current',path/'skills/current.json'),('candidate',path/'candidate.json')]:
        row=read(p)
        if row: data['skills'][label]=row
    for p in sorted((path/'diagnostics').glob('*.json')):
        row=read(p)
        if row and isinstance(row.get('metric'),str):
            valid=all(isinstance(row.get(key,{}),dict) for key in ('scores','evidence','presentation'))
            valid=valid and all(isinstance(row.get(key,[]),list) for key in ('task_ids','trace_refs'))
            evidence=row.get('evidence') or {}
            valid=valid and all(isinstance(evidence.get(key,[]),list) and all(isinstance(item,dict) for item in evidence.get(key,[])) for key in ('rules','judgments','phrases','chunks','matches'))
            if not valid:
                warnings.append(f'{p.name}: 진단 형식이 올바르지 않아 표시하지 않습니다.');continue
            row.pop('calls',None);data['diagnostics'].append(row)
    for stage in ('no_skill','parent','candidate'):
        folder=path/'external_evaluation'/stage
        if not folder.exists(): continue
        raw=read(folder/'evaluation.json')
        record={'status':'incomplete','traces':traces(folder/'traces.jsonl')}
        if raw and isinstance(raw.get('result',raw),dict):
            result=raw.get('result',raw)
            if type(result.get('correct')) is int and type(result.get('n')) is int and 0<=result['correct']<=result['n']:
                record.update(status='complete',result=result,skill_hash=raw.get('skill_hash'))
            else: warnings.append(f'{stage}: 평가 수치가 올바르지 않습니다.')
        failure=read(folder/'failure.json')
        if failure:
            record.update(status='failed',failure=failure)
            warnings.append(f"{stage}: 평가 실패 — {failure.get('error','원인 기록 없음')}")
        data['evaluation'][stage]=record
    log=path.parent/'rounds.jsonl'
    if log.exists() and not log.is_symlink():
        try:
            for line in log.read_text().splitlines():
                row=json.loads(line)
                output=row.get('skillaxe',{}).get('output','')
                if Path(output).name==path.name and row.get('round')==manifest.get('round'):
                    data['round_summary']=row
        except (ValueError,OSError,AttributeError): warnings.append('round 요약을 읽을 수 없습니다.')
    return data
