"""저장한 스킬을 읽고 동결 시점의 내용 해시와 일치하는지 확인한다."""
import json
from pathlib import Path

from .contracts import SkillVersion


def load_skill(path: Path) -> SkillVersion:
    """동결된 문서를 실수로 수정했거나 부분 저장된 경우 실행 전에 거부한다.

    사용자가 직접 제공한 해시 없는 스킬 JSON도 기존처럼 읽을 수 있다. 생성기로
    만든 문서에는 generation.json이 있으므로 그 파일의 frozen 상태와 해시도
    확인한다. 이 검사는 실수 방지용이며 파일을 악의적으로 바꾸지 못하게 하는
    서명/권한 보안 장치는 아니다.
    """
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("skill must be a JSON object")
    expected = raw.pop("content_hash", None)
    skill = SkillVersion(**raw)
    if expected is not None and expected != skill.content_hash:
        raise ValueError("skill content hash does not match the saved version")
    provenance = path.parent / "generation.json"
    if provenance.is_file():
        record = json.loads(provenance.read_text(encoding="utf-8"))
        if record.get("status") != "frozen":
            raise ValueError("skill generation did not finish and freeze")
        if record.get("content_hash") != skill.content_hash:
            raise ValueError("skill content hash differs from frozen generation")
    return skill


CONTENT_FIELDS = ('description', 'applies_when', 'avoid_when', 'body')


def document_content(skill):
    from dataclasses import asdict
    value=asdict(skill)
    return {k:value[k] for k in CONTENT_FIELDS}


def candidate_skill(content, current):
    """모델은 내용만 반환한다. 식별자·부모·다음 버전은 프로그램이 부여한다."""
    import re
    value=json.loads(content)
    if not isinstance(value,dict) or set(value)!=set(CONTENT_FIELDS)|{'changes'}:
        raise ValueError('candidate must contain four document fields and changes')
    for field in ('applies_when','avoid_when'):
        if not isinstance(value[field],list): raise ValueError('condition fields must be arrays')
    if not isinstance(value['changes'],list): raise ValueError('changes must be an array')
    for change in value['changes']:
        if not isinstance(change,dict) or set(change)!={'diagnosis_ids','rule_ids','reason'}: raise ValueError('invalid change record')
        if not isinstance(change['reason'],str) or not change['reason'].strip(): raise ValueError('change reason required')
        for field in ('diagnosis_ids','rule_ids'):
            if not isinstance(change[field],list) or any(not isinstance(x,str) for x in change[field]): raise ValueError('invalid references')
        if not change['diagnosis_ids']: raise ValueError('diagnosis reference required')
    if not re.fullmatch(r'L\d+',current.version): raise ValueError('expected L<number> skill version')
    return SkillVersion(skill_id=current.skill_id,version=f'L{int(current.version[1:])+1}',
                        parent_hash=current.content_hash,**{k:value[k] for k in CONTENT_FIELDS})


def validate_candidate(content,current,brief):
    candidate=candidate_skill(content,current)
    value=json.loads(content)
    diagnoses={d['diagnosis_id']:d for d in brief['diagnoses']}
    for change in value['changes']:
        if any(ref not in diagnoses for ref in change['diagnosis_ids']): raise ValueError('unknown diagnosis reference')
        rules={r['rule_id'] for ref in change['diagnosis_ids'] for r in diagnoses[ref]['evidence'].get('rules',[])}
        if any(ref not in rules for ref in change['rule_ids']): raise ValueError('unknown rule reference')
    if document_content(candidate)!=document_content(current) and not value['changes']:
        raise ValueError('changed document requires evidence-linked explanation')
    return candidate
