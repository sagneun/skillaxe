import json
import unittest
from methods.skillaxe.tests.test_execution import SequenceClient
from methods.skillaxe.contracts import SkillVersion, TaskInput

class AxesTests(unittest.TestCase):
    def test_trigger_distances_and_missing_values(self):
        from methods.skillaxe.diagnostics.trigger import trigger_scores
        scores = trigger_scores([[1, 0], [0, 1]], [[-1, 0]])
        self.assertAlmostEqual(scores['coverage_breadth'], 1)
        self.assertAlmostEqual(scores['negative_specificity'], 1)
        self.assertAlmostEqual(scores['boundary_sharpness'], 1)
        self.assertIsNone(trigger_scores([[1, 0]], [])['coverage_breadth'])
        self.assertIsNone(trigger_scores([[1, 0]], [])['boundary_sharpness'])

    def test_compliance_filters_relevance_and_preserves_agent_fault(self):
        from methods.skillaxe.diagnostics.compliance import aggregate
        rows = [dict(rule_id='r1', severity=2, relevant=True, a=0.3, g=1., f=0.),
                dict(rule_id='r2', severity=1, relevant=True, a=1., g=0.8, f=1.),
                dict(rule_id='r3', severity=3, relevant=False, a=0., g=0.2, f=1.)]
        scores = aggregate(rows)
        self.assertAlmostEqual(scores['compliance'], 1.4/3)
        self.assertAlmostEqual(scores['skill_score'], 2.8/3)
        self.assertIsNone(aggregate([])['compliance'])

    def test_coverage_uses_best_chunk_per_path(self):
        from methods.skillaxe.diagnostics.coverage import coverage_scores
        result = coverage_scores([[1, 0], [-1, 0]], [[1, 0], [0, 1]])
        self.assertEqual(result['best_chunk_indices'], [0, 1])
        self.assertAlmostEqual(result['path_coverage'], 0.5)

    def test_bad_vectors_are_rejected(self):
        from methods.skillaxe.embeddings import cosine
        for a,b in [([0,0],[1,0]), ([1],[1,2]), ([float('nan')],[1])]:
            with self.assertRaises(ValueError): cosine(a,b)

    def test_chunk_offsets_cover_paragraphs_and_hard_limit(self):
        from methods.skillaxe.diagnostics.coverage import split_chunks
        body = '# Rules\n\n' + 'abcdefghij'*5 + '\n\nSecond paragraph.'
        chunks = split_chunks(body, max_chars=20)
        for chunk in chunks:
            self.assertEqual(body[chunk['start']:chunk['end']], chunk['text'])
            self.assertLessEqual(len(chunk['text']),20)
        self.assertTrue(any('Second' in c['text'] for c in chunks))

if __name__ == '__main__': unittest.main()

class ParserRegressionTests(unittest.TestCase):
    def test_local_without_does_not_negate_positive_scope(self):
        try:
            import en_core_web_sm
        except ImportError:
            self.skipTest('optional parser model not installed')
        from methods.skillaxe.diagnostics.trigger import TriggerParser
        parser=TriggerParser('en_core_web_sm','3.8.0')
        skill=SkillVersion('scope','L0','Use this skill for SQLite queries without missing tables.','Keep valid tables.')
        phrases=parser.extract(skill)
        positive=[p['text'] for p in phrases if p['polarity']=='positive']
        self.assertTrue(any('SQLite' in p or 'queries' in p for p in positive))
        self.assertNotIn('this skill',[p['text'] for p in phrases])

class KoreanParserTests(unittest.TestCase):
    def test_korean_phrases_and_explicit_exclusions_preserve_source_offsets(self):
        try:
            import ko_core_news_sm
        except ImportError:
            self.skipTest('Korean parser not installed')
        from methods.skillaxe.diagnostics.trigger import TriggerParser
        parser=TriggerParser('ko_core_news_sm','3.8.0')
        skill=SkillVersion('ko','L0','SQLite 데이터 조회와 결제 집계를 수행합니다.','절차',avoid_when=('데이터를 수정하는 요청에는 사용하지 않습니다.',))
        phrases=parser.extract(skill)
        self.assertTrue(any(p['polarity']=='positive' for p in phrases))
        self.assertTrue(any(p['polarity']=='negative' for p in phrases))
        for p in phrases:
            source=skill.description if p['field']=='description' else skill.avoid_when[0]
            self.assertEqual(source[p['start']:p['end']],p['text'])
    def test_korean_grammatical_negation(self):
        try:
            import ko_core_news_sm
        except ImportError:
            self.skipTest('Korean parser not installed')
        from methods.skillaxe.diagnostics.trigger import TriggerParser
        skill=SkillVersion('ko','L0','결제 집계를 제외합니다.','절차')
        phrases=TriggerParser('ko_core_news_sm','3.8.0').extract(skill)
        self.assertTrue(phrases)
        self.assertTrue(all(p['polarity']=='negative' for p in phrases))
