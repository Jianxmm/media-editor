import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from workspace_tools import render_review


class ReviewRecordTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'issues.json'
        self.output = self.root / 'out/review.md'

    def issue(self, ident, **kwargs):
        return dict(id=ident, priority='P1', location='00:30', original='原始机器句',
                    question='具体疑点', draft='正文实际一句', **kwargs)

    def render(self, items):
        self.source.write_text(json.dumps({'issues': items}, ensure_ascii=False))
        before = self.source.read_bytes()
        result = render_review(self.source, self.output)
        self.assertEqual(self.source.read_bytes(), before)
        return result, self.output.read_text()

    def test_same_place_different_facts_remain_independent_and_priority_is_global(self):
        low = self.issue('N1'); low.update(priority='P2', question='低优先问题')
        first = self.issue('N2'); first.update(question='第一项事实')
        later = self.issue('N3'); later.update(location='00:40', question='稍后重要事实')
        result, text = self.render([low, first, later])
        self.assertEqual((result['issues'], result['locations']), (3, 2))
        self.assertLess(text.index('稍后重要事实'), text.index('低优先问题'))
        self.assertIn('N1', text)
        self.assertIn('N2', text)

    def test_source_link_points_to_existing_anchor_and_rejects_missing_anchor(self):
        index = self.root / 'source.md'
        index.write_text('<a id="s12"></a>\n\n原始机器句')
        item = self.issue('Q1', source_link='source.md#s12')
        _, text = self.render([item])
        self.assertIn('../source.md#s12', text)
        self.output.unlink()
        item['source_link'] = 'source.md#not-there'
        with self.assertRaises(ValueError):
            self.render([item])
        self.assertFalse(self.output.exists())

    def test_resolved_record_requires_actual_finding_and_evidence_record(self):
        item = self.issue('Q1', status='已回听')
        with self.assertRaises(ValueError):
            self.render([item])
        self.assertFalse(self.output.exists())

    def test_asr_is_not_an_allowed_listening_method(self):
        (self.root / 'evidence.txt').write_text('synthetic test evidence, not a real hearing')
        item = self.issue('Q1', status='已回听', finding='模拟结论', review={
            'method': '辅助ASR', 'reviewer': '模拟测试', 'checked_at': '2000-01-01',
            'evidence': ['evidence.txt']})
        with self.assertRaises(ValueError):
            self.render([item])

    def test_supplied_document_review_keeps_finding_without_claiming_voice_confirmation(self):
        (self.root / 'evidence.txt').write_text('synthetic publisher name, not real media')
        item = self.issue('NAME', status='已资料核对', finding='模拟：资料名称已对应，人声未核。', review={
            'method': '资料核对', 'reviewer': '模拟夹具', 'checked_at': '2000-01-01',
            'evidence': ['evidence.txt']})
        result, text = self.render([item])
        self.assertIn('已资料核对', text)
        self.assertIn(item['finding'], text)
        self.assertIn('../evidence.txt', text)
        self.assertEqual(result['states']['已资料核对'], 1)
        self.assertNotIn('release_ready', result)

    def test_global_voice_gap_does_not_replace_individual_word_issues(self):
        whole = self.issue('VOICE', scope='global')
        whole['question'] = '全场声音边界缺口'
        word = self.issue('WORD'); word['question'] = '局部名称原词'
        result, text = self.render([whole, word])
        rows = [line for line in text.splitlines() if line.startswith('| P1 |')]
        self.assertEqual(len(rows), 1)
        self.assertIn('局部名称原词', rows[0])
        self.assertIn('全场声音边界缺口', text)
        self.assertEqual(result['global_issues'], 1)

    def test_duplicate_ids_cannot_mix_independent_decisions(self):
        with self.assertRaises(ValueError):
            self.render([self.issue('SAME'), self.issue('SAME')])

    def test_conservative_wording_is_not_reported_as_a_heard_result(self):
        (self.root / 'draft.md').write_text('正文实际一句')
        item = self.issue('SAFE', status='已保守表达', finding='模拟：删去不可靠名称，原声仍待核。', review={
            'method': '保守改写', 'reviewer': '模拟编辑', 'checked_at': '2000-01-01',
            'evidence': ['draft.md']})
        result, text = self.render([item])
        self.assertIn('已保守表达', text)
        self.assertEqual(result['states'].get('已回听', 0), 0)


if __name__ == '__main__':
    unittest.main()
