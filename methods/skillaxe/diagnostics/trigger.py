"""Dependency parser의 부정 범위와 문맥 임베딩으로 세 거리 지표를 계산한다."""
from itertools import combinations
from ..embeddings import cosine, normalize
from .common import diagnostic, unavailable


def trigger_scores(positive, negative):
    # 부족한 문구는 N/A이며 0으로 채우지 않는다.
    pairs = [1-cosine(a,b) for a,b in combinations(positive,2)]
    distances = [[1-cosine(n,p) for p in positive] for n in negative]
    return dict(coverage_breadth=sum(pairs)/len(pairs) if pairs else None,
                negative_specificity=sum(min(row) for row in distances)/len(distances) if positive and negative else None,
                boundary_sharpness=min(map(min, distances)) if positive and negative else None)


class TriggerParser:
    """영문 noun chunk 및 한국어 의존 구문의 명사구 추출. 부정/avoid/exclude 지배 구문을 기록한다.

    description과 명시적 applies_when/avoid_when을 사용한다. 실행 지침 본문을
    임의로 적용 조건으로 해석하지 않는다. 추출 규칙은 논문 공개 설정이 아닌 구현 선택.
    """
    def __init__(self, model, version):
        import spacy
        self.nlp = spacy.load(model)
        if self.nlp.meta.get('version') != version or not self.nlp.has_pipe('parser'):
            raise ValueError('parser version mismatch or dependency parser missing')
        if self.nlp.lang not in ('en','ko'):
            raise ValueError('English or Korean dependency parser required')
        self.settings = dict(model=model, version=version, spacy_version=spacy.__version__, rule='ko-dependency-nominal-negation-v1' if self.nlp.lang=='ko' else 'noun-chunk-negation-v1')

    def _korean_chunks(self, doc):
        # spaCy Korean has no noun_chunks iterator. Use nominal dependency heads
        # and their contiguous compound modifiers; offsets always reference source.
        for token in doc:
            if token.pos_ not in ('NOUN','PROPN') or token.lemma_.split('+')[0] in ('스킬','것','수','때','경우'):
                continue
            if token.dep_=='compound' and token.head.pos_ in ('NOUN','PROPN'):
                continue
            start=token.i
            while start>token.sent.start and doc[start-1].pos_ in ('NOUN','PROPN','X') and doc[start-1].dep_=='compound' and doc[start-1].head.i<=token.i:
                start-=1
            yield doc[start:token.i+1]

    def extract(self, skill):
        sources = [('description', skill.description, False)]
        sources += [(f'applies_when/{i}', s, False) for i,s in enumerate(skill.applies_when)]
        sources += [(f'avoid_when/{i}', s, True) for i,s in enumerate(skill.avoid_when)]
        phrases = []
        for field, text, excluded in sources:
            doc = self.nlp(text)
            chunks=self._korean_chunks(doc) if self.nlp.lang=='ko' else doc.noun_chunks
            for chunk in chunks:
                if chunk.root.pos_ == "PRON" or chunk.root.lemma_.lower() == "skill":
                    continue
                governing = [chunk.root, *chunk.root.ancestors]
                negative = excluded or any(
                    node.lemma_.lower() in ('avoid','exclude') or node.lower_ == 'without' or node.dep_ == 'neg' or
                    any(child.dep_ == 'neg' or child.lower_ in ('no','never') for child in node.children)
                    for node in governing)
                if self.nlp.lang=='ko':
                    negation={'않','못','안','아니','없','제외','금지','피하'}
                    negative=excluded or any(
                        bool(set(node.lemma_.split('+')) & negation) or any(
                            child.dep_ in ('aux','advmod','neg') and bool(set(child.lemma_.split('+')) & negation)
                            for child in node.children) for node in governing)
                sentence = chunk.sent
                phrases.append(dict(phrase_id=f'p{len(phrases)+1}', text=chunk.text, context=sentence.text,
                                    polarity='negative' if negative else 'positive', field=field,
                                    start=chunk.start_char, end=chunk.end_char,
                                    context_start=sentence.start_char, context_end=sentence.end_char))
        return phrases


def diagnose_trigger(skill, embeddings, parser, alpha=0.5):
    if type(alpha) not in (int,float) or not 0 <= alpha <= 1:
        raise ValueError('alpha must be in [0,1]')
    result = diagnostic('trigger_precision', skill, config={'alpha':alpha, 'embedding':embeddings.settings, 'parser':parser.settings})
    try:
        phrases = parser.extract(skill)
        result['evidence']['phrases'] = phrases
        vectors = embeddings.embed([s for p in phrases for s in (p['text'],p['context'])]) if phrases else []
        if len(vectors) != 2*len(phrases): raise ValueError('embedding count mismatch')
        groups = {'positive':[], 'negative':[]}
        ids = {'positive':[], 'negative':[]}
        for i,p in enumerate(phrases):
            a,b = vectors[2*i:2*i+2]
            if len(a) != len(b): raise ValueError('dimension mismatch')
            groups[p['polarity']].append(normalize([alpha*x+(1-alpha)*y for x,y in zip(a,b)]))
            ids[p['polarity']].append(p['phrase_id'])
        pos, neg = groups['positive'], groups['negative']
        result['scores'] = trigger_scores(pos,neg)
        result['evidence']['na_reasons'] = {k: 'Insufficient positive/negative phrases for this metric.'
                                           for k,v in result['scores'].items() if v is None}
        if pos and neg:
            distance,i,j = min((1-cosine(p,n),i,j) for i,p in enumerate(pos) for j,n in enumerate(neg))
            result['evidence']['nearest_pair'] = dict(positive=ids['positive'][i], negative=ids['negative'][j], distance=distance)
        if all(v is None for v in result['scores'].values()): result['status']='na'
        return result
    except Exception as exc:
        return unavailable(result,exc)
