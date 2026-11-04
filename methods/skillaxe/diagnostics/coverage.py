"""경로 후보와 문단의 최대 코사인 유사도를 평균한다. 정답률이 아니다."""
import re
from ..embeddings import cosine
from ..contracts import require_text
from .common import diagnostic, ask_json, unavailable


def split_chunks(body, max_chars=1200):
    if type(max_chars) is not int or max_chars < 1: raise ValueError('invalid chunk length')
    chunks=[]
    for match in re.finditer(r'\S(?:.*?\S)?(?=\n\s*\n|\Z)',body,re.S):
        start,end=match.span()
        for offset in range(start,end,max_chars):
            stop=min(offset+max_chars,end)
            chunks.append(dict(chunk_id=f'c{len(chunks)+1}',text=body[offset:stop],start=offset,end=stop))
    if not chunks: raise ValueError('empty skill body')
    return chunks


def coverage_scores(paths,chunks):
    if not paths or not chunks: raise ValueError('paths/chunks must not be empty')
    matrix=[[cosine(path,chunk) for chunk in chunks] for path in paths]
    indices=[max(range(len(row)),key=row.__getitem__) for row in matrix]
    scores=[row[i] for row,i in zip(matrix,indices)]
    return dict(path_coverage=sum(scores)/len(scores),best_chunk_indices=indices,similarities=scores)


def diagnose_coverage(task,skill,judge,embeddings,*,skill_type='SQLite Text-to-SQL',path_count=3,max_chars=1200,paths=None):
    result=diagnostic('solution_path_coverage',skill,[task.task_id],config={
        'embedding':embeddings.settings,'path_count':path_count,'max_chars':max_chars,'overlap':0,'skill_type':skill_type})
    try:
        if type(path_count) is not int or path_count < 1: raise ValueError('invalid path count')
        if paths is None:
            # 스킬 본문과 생성 SQL은 경로 후보 생성에 전달하지 않는다.
            value=ask_json(judge,'coverage_paths',{'question':task.question,'schema':task.schema,
                           'skill_type':skill_type,'path_count':path_count},result)
            paths=value['paths']
        if not isinstance(paths,list) or len(paths)!=path_count: raise ValueError('path count mismatch')
        for path in paths: require_text('path',path)
        if len(set(paths))!=len(paths): raise ValueError('duplicate paths')
        chunks=split_chunks(skill.body,max_chars)
        result['evidence'].update(paths=paths,chunks=chunks)
        vectors=embeddings.embed(paths+[c['text'] for c in chunks])
        if len(vectors)!=len(paths)+len(chunks): raise ValueError('embedding count mismatch')
        scores=coverage_scores(vectors[:len(paths)],vectors[len(paths):])
        result['scores']={'path_coverage':scores['path_coverage']}
        result['evidence']['matches']=[dict(path_id=f'path{i+1}',path=path,chunk_id=chunks[c]['chunk_id'],similarity=score)
                                      for i,(path,c,score) in enumerate(zip(paths,scores['best_chunk_indices'],scores['similarities']))]
        result['uncertainty']=['Generated paths are unverified candidates; similarity does not establish SQL correctness.']
        return result
    except Exception as exc:
        return unavailable(result,exc)
