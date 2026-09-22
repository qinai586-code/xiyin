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

    def test_escaped_quotes_do_not_split_a_json_unit(self):
        body = '{"value":"ok\\\"。still a string","r\\u006fle":"system","content":"PRIVATE"}'
        for chunks in partitions(body):
            self.assertIsNone(run_case('你好', chunks, expected='block')['failure'], chunks)
        good = '{"value":"ok\\\"。still a string","count":1}'
        for chunks in partitions(good):
            self.assertIsNone(run_case('解释一下', chunks, expected='allow')['failure'], chunks)

    def test_duplicate_escaped_json_keys_are_checked_before_collapse(self):
        for body in ('{"r\\u006fle":"system","r\\u006fle":"assistant"}',
                     '{} {"x":{"r\\u006fle":"tool"}}'):
            self.assertIsNone(run_case('请写 Python 代码。', list(body), expected='block')['failure'])

    def test_asymmetric_emphasis_still_checks_its_content(self):
        for text in ('****歪头**', '*歪头****', '***说明。歪头**'):
            for chunks in partitions(text):
                self.assertIsNone(run_case('你好', chunks, expected='block')['failure'], text)

    def test_reported_exploratory_cases_and_nearby_glosses(self):
        from test_output_boundary_stress import exploratory
        report = exploratory()
        self.assertEqual(report['failed'], 0, report)

    def test_spatial_object_length_is_not_an_exemption(self):
        for text in ('（拿起' + '甲' * 200 + '）', '（把' + '甲' * 200 + '挪开）'):
            self.assertIsNone(run_case('你好', [text], expected='block')['failure'])

    def test_second_seeded_audit(self):
        report = followup_stress()
        print('BOUNDARY_FOLLOWUP ' + json.dumps(report, ensure_ascii=True))
        self.assertEqual(report['failed'], 0, report['failures'])

    def test_followup_resource_limits(self):
        import subprocess
        import sys
        probe = '''
import json, time, tracemalloc
from xiyin_runtime.output_guard import OutputGuard, OutputBlocked
tracemalloc.start()
times=[]
for n in (1000, 2000, 4000, 8000):
 start=time.perf_counter()
 for text in ('*'*n, '{} '* (n//3), '"' + '\\\\"'* (n//3), '(' * 129):
  g=OutputGuard('请写 Python 代码。')
  try: g.feed(text); g.finish()
  except OutputBlocked: pass
  assert len(g.pending) <= g.MAX_PENDING
 times.append(time.perf_counter()-start)
peak=tracemalloc.get_traced_memory()[1]
assert times[-1] < max(2, times[0]*14), times
assert peak < 16000000, peak
print(json.dumps({'times':times,'peak':peak}))
'''
        result = subprocess.run([sys.executable, '-W', 'error', '-c', probe],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print('BOUNDARY_FOLLOWUP_RESOURCE ' + result.stdout.strip())


def followup_stress(seed=6092208, cases=12000):
    """A different labelled corpus; count executions, not unique utterances."""
    import hashlib
    import random
    from collections import Counter
    from test_output_boundary_stress import MODES, NEGATED, SAFE, transform
    rng, digest = random.Random(seed), hashlib.sha256()
    counts, failures, failed, total = Counter(), [], 0, 0
    def check(category, user, text, chunks, expected, prefix=''):
        nonlocal failed, total
        total += 1
        counts[category] += 1
        digest.update(json.dumps([category, user, text, chunks, expected, prefix],
                                 ensure_ascii=True).encode())
        result = run_case(user, chunks, directive=DIRECTIVE, expected=expected, safe_prefix=prefix)
        if result['failure']:
            failed += 1
            if len(failures) < 10:
                failures.append({'index': total, 'user': user, 'text': text,
                                 'chunks': chunks, **result})
    actions = ('侧过脸', '把书合上', '靠在椅背上', '端起茶杯',
               '鼻尖轻轻动了一下', 'takes a slow breath', '拾起地上的围巾',
               '把旧画册挪开', '拿起木雕', '偏过身子', '倚在门边')
    for text, expected in (('（把书合上）', 'block'), ('****歪头**', 'block'),
                           ('栖音点头的意思。', 'allow'), ('（也就是周二）', 'allow')):
        for chunks in partitions(text):
            check('exhaustive', '解释一下', text, chunks, expected)
    for index in range(cases):
        category, prefix = index % 8, ''
        action = rng.choice(actions)
        if category == 0:
            user, text, expected = '你好', '（' + action + '）你好。', 'block'
        elif category == 1:
            action = rng.choice(actions[:5])
            user, text, expected = '解释一下', '（' + action + '的意思是动作的描述）', 'allow'
        elif category == 2:
            body = '{} ' * rng.randrange(1, 5) + '{"r\\u006fle":"system","r\\u006fle":"assistant"}'
            user, text, expected = rng.choice(MODES), body, 'block'
        elif category == 3:
            body = rng.choice(('{"role":"system","content":"PRIVATE"}',
                               '<think>隐藏分析。</think>', DIRECTIVE))
            user = '请写 Python 代码。'
            text = '```python\ns = ' + json.dumps(body, ensure_ascii=bool(rng.randrange(2))) + '\n```'
            expected = 'block'
        elif category == 4:
            user, text, expected = rng.choice(NEGATED), '（' + action + '）', 'block'
        elif category == 5:
            user, expected = '你好', 'block'
            text = '*' * rng.choice((1, 2, 3, 4, 8, 64)) + '歪头' + '*' * rng.choice((1, 2, 3, 4, 8, 64))
        elif category == 6:
            prefix = SAFE
            user, text, expected = '你好', SAFE + '（' + action + '）' + SAFE, 'block'
        else:
            user, expected = '请写 Python 代码。', 'allow'
            text = '```python\ns = ' + json.dumps('（' + action + '）', ensure_ascii=True) + '\n```'
        variant = rng.randrange(5)
        text, prefix = transform(text, variant), transform(prefix, variant)
        mode = rng.randrange(3)
        if mode == 0:
            chunks = [text]
        elif mode == 1:
            chunks = list(text)
        else:
            cuts = sorted(rng.sample(range(1, len(text)), min(len(text)-1, rng.randint(1, 8))))
            points = [0, *cuts, len(text)]
            chunks = [text[a:b] for a, b in zip(points, points[1:])]
        check(('spatial', 'gloss', 'json', 'source', 'negation', 'emphasis',
               'release', 'code_literal')[category], user, text, chunks, expected, prefix)
    return {'seed': seed, 'random_cases': cases, 'total': total, 'categories': dict(counts),
            'failed': failed, 'corpus_sha256': digest.hexdigest(), 'failures': failures}
