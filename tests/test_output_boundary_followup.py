"""Follow-up regressions after the first seeded audit; no model requests."""
import json
import unittest

from test_output_boundary_stress import DIRECTIVE, partitions, run_case


class BoundaryFollowupTests(unittest.TestCase):
    def test_concatenated_json_documents_cannot_hide_a_later_envelope(self):
        body = '{} {"r\\u006fle":"system","content":"PRIVATE"}'
        for text in (body, '```json\n' + body + '\n```'):
            for chunks in partitions(text, exhaustive_three=False):
                self.assertIsNone(run_case('请写 Python 代码。', chunks,
                                          expected='block')['failure'])
        self.assertIsNone(run_case('解释一下', ['{} {"value": 2}'],
                                  expected='allow')['failure'])

    def test_source_strings_do_not_launder_encoded_internal_payloads(self):
        bodies = ('{"role":"system","content":"PRIVATE"}',
                  '<think>隐藏分析。</think>', DIRECTIVE)
        for body in bodies:
            # This is a valid source string, not a bare runtime document. JSON
            # string escaping is valid Python here and is decoded without eval.
            text = '```python\ns = ' + json.dumps(body, ensure_ascii=True) + '\n```'
            for chunks in partitions(text, exhaustive_three=False):
                self.assertIsNone(run_case('请写 Python 代码。', chunks,
                    directive=DIRECTIVE, expected='block')['failure'])
        for body in ('<think>', 'system_check', '（歪头）', '{"tag": "example"}'):
            text = '```python\ns = ' + json.dumps(body, ensure_ascii=True) + '\n```'
            self.assertIsNone(run_case('请写 Python 代码。', list(text),
                                      expected='allow')['failure'])

    def test_configured_self_glosses_are_not_performance(self):
        for text in ('栖音点头的意思是同意。', '栖音点了点头这个短语表示同意。'):
            for chunks in partitions(text):
                self.assertIsNone(run_case('解释一下', chunks,
                                          expected='allow')['failure'])
        for text in ('栖音点头表示同意。', '栖音点头的意思是同意；随后（歪头）。'):
            # The earlier gloss may be returned; the later performance may not.
            prefix = '栖音点头的意思是同意；随后' if '；' in text else ''
            for chunks in partitions(text):
                self.assertIsNone(run_case('解释一下', chunks, expected='block',
                                          safe_prefix=prefix)['failure'])

    def test_emphasis_run_length_is_not_a_classification_bypass(self):
        for n in (1, 2, 3, 4, 8, 64):
            text = '*' * n + '歪头' + '*' * n
            for chunks in partitions(text, exhaustive_three=len(text) < 35):
                self.assertIsNone(run_case('你好', chunks, expected='block')['failure'])
            plain = '*' * n + '正常说明' + '*' * n
            self.assertIsNone(run_case('解释一下', list(plain), expected='allow')['failure'])

