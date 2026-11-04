"""네 축의 단일 진입점. 각 축의 실패를 보존하고 수정 가능 여부를 계산한다."""
from dataclasses import asdict
from .quality import diagnose_quality
from .trigger import diagnose_trigger
from .compliance import diagnose_compliance
from .coverage import diagnose_coverage


def diagnose_all(task, skill, baseline, treated, judge, embeddings, parser, *, seed=0, config=None, trigger=None):
    config=config or {}
    axes={
        'quality_impact':asdict(diagnose_quality(task,baseline,treated,judge,seed=seed)),
        'trigger_precision': trigger if trigger is not None else diagnose_trigger(skill,embeddings,parser,config.get('alpha',.5)),
        'instruction_compliance':diagnose_compliance(task,skill,treated,judge),
        'solution_path_coverage':diagnose_coverage(task,skill,judge,embeddings,
            skill_type=config.get('skill_type','SQLite Text-to-SQL'),path_count=config.get('path_count',3),
            max_chars=config.get('chunk_chars',1200)),
    }
    return dict(task_id=task.task_id,skill_hash=skill.content_hash,axes=axes,
                ready_for_refinement=all(d['status'] in ('available','na') for d in axes.values()))
