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


def ask_json(client, prompt, payload, result):
    instructions = (Path(__file__).parents[1] / 'prompts' / (prompt+'.md')).read_text()
    call = recorded_call(client, [{'role':'system','content':instructions},
                                 {'role':'user','content':json.dumps(payload, ensure_ascii=False, allow_nan=False)}], prompt)
    result['calls'].append(asdict(call))
    if call.status != 'success':
        raise ValueError('model_call_failed')
    value = json.loads(call.response)
    if not isinstance(value, dict):
        raise ValueError('expected JSON object')
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
