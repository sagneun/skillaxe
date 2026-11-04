"""네 진단을 근거 그대로 묶는다. 정답 점수·원 호출 메시지는 Refiner에 전달하지 않는다."""
from uuid import uuid4


def build_brief(reports):
    diagnoses={}
    for report in reports:
        for name, d in report['axes'].items():
            evidence=dict(d.get('evidence',{}))
            if name=='instruction_compliance':
                relevant=[r for r in evidence.get('judgments',[]) if r['relevant']]
                ids={r['rule_id'] for r in relevant}
                evidence['rules']=[r for r in evidence.get('rules',[]) if r['rule_id'] in ids]
                evidence['judgments']=relevant
            if name=='quality_impact':
                evidence={'direction':d['direction_evidence'],'magnitude':d['magnitude_evidence']}
            diagnoses[d['diagnosis_id']]={
                'diagnosis_id':d['diagnosis_id'],'metric':name,'status':d['status'],
                'task_ids':d['task_ids'],'scores':d.get('scores',{'quality':d.get('score')}),
                'evidence':evidence,'uncertainty':d.get('uncertainty_reasons',d.get('uncertainty',[]))}
    return dict(brief_id=str(uuid4()),ready=bool(reports) and all(r['ready_for_refinement'] for r in reports),
                diagnoses=list(diagnoses.values()),
                instructions=[
                    'Preserve clear rules with f=0; do not weaken them merely because the agent failed.',
                    'Use trigger distances to clarify applicability, not as routing accuracy.',
                    'Low-coverage paths are unverified suggestions; state applicability conditions.',
                    'Do not combine the diagnostic scores into a single reward.',
                    'Reconcile conflicting observations explicitly. If evidence is insufficient, leave the skill unchanged.'])
