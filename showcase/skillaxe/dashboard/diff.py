"""Compare only recorded skill documents."""
import difflib


def skill_text(skill):
    labels={'description':'스킬 설명','applies_when':'적용 조건','avoid_when':'제외 조건','body':'실행 절차'}
    sections=[]
    for key in ('description','applies_when','avoid_when','body'):
        value=skill.get(key,'')
        if isinstance(value,list): value='\n'.join('- '+item for item in value) or '명시된 조건 없음'
        sections.append(f'## {labels[key]}\n\n{value}')
    return '\n\n'.join(sections)


def skill_diff(skills):
    if 'current' not in skills or 'candidate' not in skills: return '수정 후보가 없습니다. 문서 비교는 아직 실행되지 않았습니다.'
    return '\n'.join(difflib.unified_diff(skill_text(skills['current']).splitlines(),skill_text(skills['candidate']).splitlines(),fromfile=skills['current'].get('version','current'),tofile=skills['candidate'].get('version','candidate'),lineterm='')) or '문서 변경 없음'
