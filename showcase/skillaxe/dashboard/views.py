"""Pure presentation transforms: no IO, model calls, or fabricated scores."""
import json

STATUS={'available':'계산 완료','unavailable':'판정 불가','na':'N/A','complete':'완료','partial':'부분 완료','running':'진행 중','diagnosis_unavailable':'진단 실패로 중단','failed':'실패','success':'실행 성공'}
AXES={'quality_impact':'품질 영향','trigger_precision':'적용 조건','instruction_compliance':'지침 준수','solution_path_coverage':'해결 경로'}
LABELS={'Quality':'품질 영향','coverage_breadth':'적용 범위','negative_specificity':'제외 조건 구체성','boundary_sharpness':'경계 선명도','compliance':'지침 준수 점수','skill_score':'책임 보정 점수','path_coverage':'해결 경로 포함도','preference':'선호 결과','direction':'변화 방향','magnitude':'변화 크기','direction_evidence':'방향 판단 근거','magnitude_evidence':'크기 판단 근거'}


def esc(value):
    if value is None: return 'N/A'
    if isinstance(value,bool):return '예' if value else '아니오'
    if isinstance(value,float): return f'{value:.4f}'
    return str(value).replace('|','\\|').replace('<','&lt;').replace('>','&gt;').replace('\n',' ')


def table(headers,rows):
    return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join('---' for _ in headers)+' |']+['| '+' | '.join(esc(c) for c in row)+' |' for row in rows])


def code(value,language='json'):
    text=value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,indent=2)
    fence='`'*max(3,max((len(x) for x in __import__('re').findall(r'`+',text)),default=0)+1)
    return f'\n{fence}{language}\n{text}\n{fence}\n'


def score(data,stage):
    record=data['evaluation'].get(stage,{})
    if record.get('status')=='failed': return '실패'
    if record.get('status')=='incomplete': return '평가 미완료'
    result=record.get('result')
    return f"{result['correct']} / {result['n']}" if result else '미실행'


def outcome(data):
    summary=data.get('round_summary') or {}
    if not data['skills'].get('candidate'): return '아직 진화한 스킬이 없습니다. 진단 상태를 확인하세요.'
    before=data['evaluation'].get('parent',{}).get('result',{})
    after=data['evaluation'].get('candidate',{}).get('result',{})
    change=f"초기 스킬 대비 {after['correct']-before['correct']:+d}문제. " if before and after and before['n']==after['n'] else ''
    if summary.get('accepted') is True: return change+'최종 채택된 스킬입니다.'
    if summary.get('accepted') is False: return change+'채택 기준 미달로 초기 스킬을 유지했습니다. 아래는 생성된 진화 후보의 결과입니다.'
    return change+'최종 채택 여부는 아직 기록되지 않았습니다.'


def sql_view(data,stage,task_id):
    record=data['evaluation'].get(stage,{})
    trace=next((t for t in record.get('traces',[]) if t.get('task_id')==task_id and t.get('replicate')==1),None)
    if trace is None: return '이 작업의 실행 결과가 없습니다.'
    text=code(trace.get('sql',''),'sql')
    result=next((p for p in record.get('result',{}).get('per_problem',[]) if p.get('id')==task_id),None)
    if result: text+='\n**'+('정답' if result['correct'] else '오답')+'** · '+esc(result.get('error') or '오류 없음')+'\n'
    ev=trace.get('execution') or {}
    if ev.get('columns'): text+='\n'+table([str(c) for c in ev['columns']],ev.get('rows',[]))
    if ev.get('rows_truncated') or ev.get('cells_truncated'): text+='\n일부 결과만 표시한 표본입니다.'
    return text


def diagnostic_view(data,metric,task_id):
    rows=[d for d in data['diagnostics'] if d.get('metric')==metric and (not d.get('task_ids') or task_id in d['task_ids'])]
    if not rows: return '이 작업의 진단 기록이 없습니다. 점수를 추정하지 않습니다.'
    out=[]
    for d in rows:
        out.append(f"**{STATUS.get(d.get('status'),d.get('status'))}**")
        if d.get('error'): out.append(f"오류: {esc(d['error'])}")
        scores=d.get('scores',{'Quality':d.get('score')})
        out.append(table(['지표','값'],[(LABELS.get(k,k),v) for k,v in scores.items()]))
        e=d.get('evidence',{})
        if metric=='quality_impact':
            out.append(table(['판단','기록'],[(LABELS[k],{'tie':'동률'}.get(d.get(k),d.get(k))) for k in ('preference','direction','magnitude','direction_evidence','magnitude_evidence')]))
            out.append(table(['제시 순서','조건'],[[label,v.get('condition')] for label,v in d.get('presentation',{}).items()]))
        elif metric=='instruction_compliance':
            judged=e.get('judgments',[])
            out.append(table(['규칙','관련성','심각도','준수 a','품질 g','책임 f','보정 c','증거 부족'],[[r.get(k) for k in ('rule_id','relevant','severity','a','g','f','c','insufficient_evidence')] for r in judged]))
            for r in judged or e.get('rules',[]):
                out.append(f"**{esc(r.get('rule_id'))}** {esc(r.get('rule'))}\n\n근거: {esc(r.get('evidence',r.get('source_quote')))}")
            out.append('보존 규칙: '+', '.join(e.get('preserve_rule_ids',[])))
        elif metric=='solution_path_coverage':
            chunks={c['chunk_id']:c for c in e.get('chunks',[])}
            for match in e.get('matches',[]):
                out.append(f"**{esc(match.get('path_id'))}** · cosine {esc(match.get('similarity'))}\n\n{esc(match.get('path'))}")
                out.append(code(chunks.get(match.get('chunk_id'),{}).get('text','청크 없음'),'text'))
            out.append('LLM이 제안한 미검증 경로입니다. cosine 유사도는 정답률이 아닙니다.')
        else:
            out.append('적용/제외 문구와 원문 위치 · 실제 스킬 선택 정확도가 아닌 문구 간 거리입니다.')
            out.append(table(['문구','적용/제외','원문'],[[p.get('text'),{'positive':'적용','negative':'제외'}.get(p.get('polarity'),p.get('polarity')),p.get('context')] for p in e.get('phrases',[])]))
            for metric,reason in e.get('na_reasons',{}).items(): out.append(f"{LABELS.get(metric,metric)}: N/A — 적용·제외 문구가 충분하지 않아 계산할 수 없습니다.")
        uncertainty=d.get('uncertainty_reasons',d.get('uncertainty',[]))
        if uncertainty: out.append('불확실성: '+esc(uncertainty))

    return '\n\n'.join(out)

