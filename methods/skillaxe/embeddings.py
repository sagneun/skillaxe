"""Trigger/Coverage가 공유하는 실제 임베딩과 수학 연산. 모델은 명시적으로 고정한다."""
import math
import re
from pathlib import Path
from .contracts import content_hash
from .records import write_json
import json


def normalize(vector):
    values = [float(x) for x in vector]
    if not values or not all(math.isfinite(x) for x in values):
        raise ValueError('embedding must be a finite nonempty vector')
    norm = math.sqrt(sum(x*x for x in values))
    if not math.isfinite(norm) or norm == 0:
        raise ValueError('embedding must have nonzero finite norm')
    return [x/norm for x in values]


def cosine(a, b):
    a, b = normalize(a), normalize(b)
    if len(a) != len(b):
        raise ValueError('embedding dimensions differ')
    return max(-1., min(1., sum(x*y for x,y in zip(a,b))))


class SentenceEmbeddings:
    def __init__(self, model, revision, cache_dir, max_length=256):
        if not re.fullmatch(r'[0-9a-f]{40}', revision):
            raise ValueError('embedding revision must be an immutable 40-character commit SHA')
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(model, revision=revision)
        self.model.max_seq_length = max_length
        self.cache = Path(cache_dir)
        self.settings = dict(model=model, revision=revision, dimension=self.model.get_sentence_embedding_dimension(),
                             max_length=max_length, normalize=True, pooling='model-defined', mode='live')

    def embed(self, texts):
        result = []
        for text in texts:
            key = content_hash({'settings': self.settings, 'text': text})
            path = self.cache / (key+'.json')
            if path.exists():
                vector = json.loads(path.read_text())
            else:
                vector = self.model.encode([text], normalize_embeddings=True)[0].tolist()
                write_json(path, vector, replace=True)
            if len(vector) != self.settings['dimension']:
                raise ValueError('cached embedding dimension mismatch')
            result.append(normalize(vector))
        return result
