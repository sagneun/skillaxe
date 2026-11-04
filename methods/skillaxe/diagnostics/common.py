"""진단의 공통 기록/JSON 호출. 각 축은 같은 provider와 기록 함수를 쓴다."""
import json
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4
from ..calls import recorded_call


def diagnostic(metric, skill, task_ids=(), trace_refs=(), config=None):
    return dict(diagnosis_id=str(uuid4()), metric=metric, skill_hash=skill.content_hash,
                task_ids=list(task_ids), trace_refs=list(trace_refs), rubric_version=metric+'-v1',
                config=config or {}, status='available', scores={}, evidence={}, calls=[],
                uncertainty=[], error=None)


def response_schema(prompt,payload):
    def obj(properties):
        return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}
    text={'type':'string'}
    if prompt=='compliance_rules':
        line_ids=list(payload['source_lines'])
        item=obj({'rule_id':text,'rule':text,'severity':{'type':'integer','enum':[1,2,3]},
                  'source_line_id':{'type':'string','enum':line_ids}})
        return obj({'rules':{'type':'array','items':item}})
    if prompt=='compliance_judge':
        item=obj({'rule_id':{'type':'string','enum':[r['rule_id'] for r in payload['rules']]},
                  'relevant':{'type':'boolean'},'a':{'type':'number','enum':[0,.3,.5,.7,1]},
                  'g':{'type':'number','enum':[.2,.4,.6,.8,1]},'f':{'type':'number','enum':[0,.3,.5,.8,1]},
                  'evidence':text,'insufficient_evidence':{'type':'boolean'}})
        return obj({'judgments':{'type':'array','items':item}})
    if prompt=='coverage_paths':
        return obj({'paths':{'type':'array','items':text,'minItems':payload['path_count'],'maxItems':payload['path_count']}})
    return None


def ask_json(client, prompt, payload, result):
    if prompt=='compliance_rules':
        lines=list(dict.fromkeys(line.strip() for line in payload['skill'].splitlines() if line.strip()))
        payload={**payload,'source_lines':{f's{i+1}':line for i,line in enumerate(lines)}}
    instructions = (Path(__file__).parents[1] / 'prompts' / (prompt+'.md')).read_text()
    call = recorded_call(client, [{'role':'system','content':instructions},
                                 {'role':'user','content':json.dumps(payload, ensure_ascii=False, allow_nan=False)}], prompt, response_schema=response_schema(prompt,payload))
    result['calls'].append(asdict(call))
    if call.status != 'success':
        raise ValueError('model_call_failed')
    value = json.loads(call.response)
    if not isinstance(value, dict):
        raise ValueError('expected JSON object')
    if prompt=='compliance_rules':
        for rule in value.get('rules',[]):
            if 'source_line_id' in rule:
                rule['source_quote']=payload['source_lines'][rule.pop('source_line_id')]
    return value


def unavailable(result, exc):
    result.update(status='unavailable', scores={}, error=type(exc).__name__)
    result['uncertainty'].append('Diagnostic failed; inspect recorded calls and model/parser installation.')
    return result


def require_trace(task, skill, trace):
    if trace.task_id != task.task_id or trace.input_hash != task.input_hash or trace.skill_hash != skill.content_hash:
        raise ValueError('trace does not match task and skill')
    if trace.status in ('generation_error', 'agent_error'):
        raise ValueError('agent execution unavailable')
