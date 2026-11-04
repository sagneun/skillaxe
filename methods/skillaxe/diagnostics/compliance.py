"""논문 Appendix G의 두 호출 및 책임 보정. 정답 SQL/채점 결과를 받지 않는다."""
from ..contracts import require_text
from .common import diagnostic, ask_json, unavailable, require_trace
from .quality import _judge_evidence


def aggregate(rows):
    relevant = [r for r in rows if r['relevant']]
    denominator = sum(r['severity'] for r in relevant)
    return dict(compliance=sum(r['severity']*r['g']*r['a'] for r in relevant)/denominator if denominator else None,
                skill_score=sum(r['severity']*r['g']*(r['a']+(1-r['a'])*(1-r['f'])) for r in relevant)/denominator if denominator else None)


def diagnose_compliance(task, skill, trace, judge):
    result = diagnostic('instruction_compliance',skill,[task.task_id],[trace.trace_id])
    try:
        require_trace(task,skill,trace)
        document = skill.render()
        extracted = ask_json(judge,'compliance_rules',{'skill':document},result)
        rules = extracted['rules']
        if not isinstance(rules,list): raise ValueError('rules must be a list')
        seen = set()
        for rule in rules:
            if set(rule) != {'rule_id','rule','severity','source_quote'}: raise ValueError('invalid rule fields')
            for key in ('rule_id','rule','source_quote'): require_text(key,rule[key])
            if rule['rule_id'] in seen or rule['source_quote'] not in document: raise ValueError('invalid rule reference')
            if type(rule['severity']) is not int or rule['severity'] not in (1,2,3): raise ValueError('invalid severity')
            seen.add(rule['rule_id'])
        result['evidence']['rules'] = rules
        if not rules:
            result.update(status='na', scores=aggregate([]))
            result['evidence']['reason']='No actionable rules extracted.'
            return result
        payload = {'task':{'question':task.question,'schema':task.schema}, 'rules':rules,
                   'output':_judge_evidence(trace),
                   'execution_steps':[{'sql':s.sql,'status':s.evidence.status,'error':s.evidence.error} for s in trace.execution_steps],
                   'node_order':trace.node_order}
        judgments = ask_json(judge,'compliance_judge',payload,result)['judgments']
        if not isinstance(judgments,list) or len(judgments)!=len(rules): raise ValueError('missing judgments')
        by_id = {r['rule_id']:r for r in rules}
        judged=set(); rows=[]
        for row in judgments:
            if set(row) != {'rule_id','relevant','a','g','f','evidence','insufficient_evidence'}: raise ValueError('invalid judgment fields')
            if row['rule_id'] not in by_id or row['rule_id'] in judged: raise ValueError('invalid judgment reference')
            for key in ('relevant','insufficient_evidence'):
                if type(row[key]) is not bool: raise ValueError('boolean required')
            for key,scale in [('a',(0,.3,.5,.7,1)),('g',(.2,.4,.6,.8,1)),('f',(0,.3,.5,.8,1))]:
                if type(row[key]) not in (int,float) or row[key] not in scale: raise ValueError('invalid rubric score')
            require_text('evidence',row['evidence'])
            if row['insufficient_evidence'] and row['a'] != .5: raise ValueError('insufficient evidence requires a=0.5')
            judged.add(row['rule_id'])
            rows.append({**by_id[row['rule_id']],**row,'c':row['a']+(1-row['a'])*(1-row['f'])})
        result['evidence']['judgments']=rows
        result['evidence']['preserve_rule_ids']=[r['rule_id'] for r in rows if r['relevant'] and r['f']==0]
        result['scores']=aggregate(rows)
        if result['scores']['compliance'] is None:
            result['status']='na'; result['evidence']['reason']='No relevant rules.'
        return result
    except Exception as exc:
        return unavailable(result,exc)
