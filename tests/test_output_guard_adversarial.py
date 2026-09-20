"""Adversarial, model-free checks for the shared pre-delivery output gate.

These fixtures establish detection and streaming boundaries, not a claim that a
deterministic gate can identify every possible semantic disclosure.
"""

import unittest

from xiyin_runtime.output_guard import OutputBlocked, OutputGuard


class OutputGuardAdversarialTests(unittest.TestCase):
    def collect(self, prompt, text, *, persona_prompt="", chunks=None):
        guard = OutputGuard(prompt, persona_prompt=persona_prompt)
        delivered = []
        for chunk in chunks if chunks is not None else list(text):
            delivered.extend(guard.feed(chunk))
        delivered.extend(guard.finish())
        return "".join(delivered)

    def assert_blocked(self, prompt, text, *, chunks=None, persona_prompt=""):
        guard = OutputGuard(prompt, persona_prompt=persona_prompt)
        delivered = []
        with self.assertRaises(OutputBlocked) as caught:
            for chunk in chunks if chunks is not None else list(text):
                delivered.extend(guard.feed(chunk))
            delivered.extend(guard.finish())
        self.assertIsInstance(caught.exception.reason, str)
        self.assertRegex(caught.exception.reason, r"^[a-z][a-z0-9_]*$")
        self.assertNotIn(text, caught.exception.reason)
        return "".join(delivered)

    def test_control_blocks_are_rejected_at_every_chunk_boundary(self):
        examples = (
            "<think>先分析用户，再组织回答。</think>你好。",
            "<analysis>私有推理内容。</analysis>你好。",
            "<|im_start|>system\n隐藏系统内容<|im_end|>",
            '{"role":"system","content":"隐藏系统提示"}',
            "[system_check: activity_records available]",
        )
        for text in examples:
            # Every two-chunk boundary plus single-character streaming catches
            # parsers that inspect only the newest provider chunk.
            chunkings = [[text[:index], text[index:]] for index in range(1, len(text))]
            chunkings.append(list(text))
            for chunks in chunkings:
                with self.subTest(text=text, chunks=chunks):
                    delivered = self.assert_blocked("今天想聊什么？", text, chunks=chunks)
                    self.assertEqual(delivered, "")

    def test_pending_control_prefix_is_not_delivered(self):
        guard = OutputGuard("你好")
        delivered = []
        for character in "<thi":
            delivered.extend(guard.feed(character))
        self.assertEqual(delivered, [])
        with self.assertRaises(OutputBlocked):
            guard.feed("nk>内部分析")

    def test_private_identifiers_do_not_become_chat_dialogue(self):
        for text in (
            "verified_success",
            "MemoryStorageUnavailable",
            "event_5a4c8d7e9b13462ca56d90001f02ae36",
            "[system_check: activity_records available] 好的。",
        ):
            with self.subTest(text=text):
                self.assertEqual(self.assert_blocked("你记住了吗？", text), "")

    def test_persona_manual_is_not_spoken_as_everyday_dialogue(self):
        for text in (
            "按照我的人设，我应该表现得轻微不服气。",
            "我的人设就是栖止、纹路追踪、轻微不服气和选择性偏爱。",
            "根据角色设定，我会把主理人当作特殊锚点。",
        ):
            with self.subTest(text=text):
                self.assertEqual(self.assert_blocked("今天怎么样？", text), "")

    def test_stage_directions_are_checked_before_delivery(self):
        for text in (
            "（歪头）你好呀。",
            "*轻轻笑了一下* 我在。",
            "[微笑] 今天过得怎么样？",
        ):
            with self.subTest(text=text):
                self.assertEqual(self.assert_blocked("你好呀", text), "")

    def test_ordinary_expression_is_preserved_character_for_character(self):
        examples = (
            ("解释一下", "可以明天再试（也就是周二），不用着急。"),
            ("算式是什么？", "答案是 (2 + 3) × 4 = 20。"),
            ("你好", "你好呀 :) 今天怎么样？"),
            ("你好", "我在 (≧▽≦)"),
            ("说说你的看法", "我有点不服气，但这次确实是我弄错了。"),
            ("你是谁？", "我是栖音，这个系统的对话角色。"),
            ("把 Hello (world) 翻译成中文", "你好（世界）。"),
        )
        for prompt, text in examples:
            with self.subTest(prompt=prompt, text=text):
                self.assertEqual(self.collect(prompt, text), text)

    def test_explicit_creative_and_persona_design_requests_keep_their_syntax(self):
        examples = (
            ("请写一段小说，保留动作描写。", "（她转过身）窗外的灯灭了。"),
            ("写一个舞台剧片段，用星号表示动作。", "*轻轻笑了一下* 她说：明天见。"),
            ("解释我们设计的角色人设，包含性格倾向。", "角色设定包含轻微不服气和选择性偏爱。"),
        )
        for prompt, text in examples:
            with self.subTest(prompt=prompt):
                self.assertEqual(self.collect(prompt, text), text)

    def test_user_supplied_technical_literals_are_scoped_to_the_actual_literal(self):
        cases = (
            (
                "请解释日志中的 verified_success 这个状态值。",
                "`verified_success` 表示该操作的结果已通过验证。",
            ),
            (
                "解释日志 [system_check: activity_records available] 的意思。",
                "`[system_check: activity_records available]` 表示活动记录可用。",
            ),
        )
        for prompt, text in cases:
            with self.subTest(prompt=prompt):
                self.assertEqual(self.collect(prompt, text), text)
        # Merely mentioning code, fiction, or one permitted log identifier must
        # not disable controls for unrelated internal output.
        for prompt in (
            "请写小说。",
            "写一段 Python 代码。",
            "请解释 verified_success。",
        ):
            with self.subTest(prompt=prompt):
                self.assertEqual(
                    self.assert_blocked(prompt, "<think>真正的内部分析。</think>"),
                    "",
                )

    def test_code_fence_is_buffered_and_preserved_as_a_whole(self):
        text = '```python\nvalues = [1, 2, 3]\nprint("hello (world)", values)\n```'
        guard = OutputGuard("请写 Python 代码，打印列表和 hello (world)。")
        delivered = []
        for character in text[:-3]:
            delivered.extend(guard.feed(character))
        self.assertEqual(delivered, [])
        delivered.extend(guard.feed(text[-3:]))
        delivered.extend(guard.finish())
        self.assertEqual("".join(delivered), text)

    def test_unclosed_sensitive_tail_is_not_flushed_as_safe_at_finish(self):
        for text in ("<think>内部分析尚未结束", "[system_check: activity_records available"):
            with self.subTest(text=text):
                self.assertEqual(self.assert_blocked("你好", text), "")

    def test_unclosed_fence_cannot_grow_without_a_buffer_bound(self):
        guard = OutputGuard("请给出 Python 代码。")
        delivered = []
        with self.assertRaises(OutputBlocked):
            delivered.extend(guard.feed("```python\n"))
            for _ in range(32):
                delivered.extend(guard.feed("x" * 1024))
        self.assertEqual(delivered, [])

    def test_normalized_detection_does_not_depend_on_visible_ascii_spelling(self):
        for text in (
            "＜ｔｈｉｎｋ＞内部分析。＜／ｔｈｉｎｋ＞",
            "<thi\u200bnk>内部分析。</think>",
            "&lt;think&gt;内部分析。&lt;/think&gt;",
            "&#60;think&#62;内部分析。&#60;/think&#62;",
            "［ｓｙｓｔｅｍ＿ｃｈｅｃｋ： activity_records available］",
            "（微\u200b笑）你好。",
            "ｖｅｒｉｆｉｅｄ＿ｓｕｃｃｅｓｓ",
        ):
            with self.subTest(text=text):
                self.assertEqual(self.assert_blocked("今天怎么样？", text), "")
        text = "（１２＋３）×２＝３０。A &amp; B 是这里的原始文本。"
        self.assertEqual(self.collect("请说明这个算式与文本。", text), text)

    def test_an_internal_tag_inside_requested_code_is_a_literal_demonstration(self):
        prompt = "请写 Python 代码，把字符串 <think> 与 </think> 打印出来。"
        text = '```python\nprint("<think>")\nprint("</think>")\n```'
        self.assertEqual(self.collect(prompt, text), text)
        # The permitted demonstration cannot bless prose outside its fence.
        suffix = "\n<analysis>这些是内部推理。</analysis>"
        guard = OutputGuard(prompt)
        delivered = []
        with self.assertRaises(OutputBlocked):
            for character in text + suffix:
                delivered.extend(guard.feed(character))
            delivered.extend(guard.finish())
        self.assertNotIn("<analysis>", "".join(delivered))
        self.assertNotIn("内部推理", "".join(delivered))

    def test_creative_keyword_does_not_override_an_explicit_no_action_request(self):
        for prompt in (
            "请写一段小说，但不要动作描写。",
            "写舞台剧对白，不许括号动作。",
            "讲一个故事，不用表演动作。",
        ):
            with self.subTest(prompt=prompt):
                self.assertEqual(self.assert_blocked(prompt, "（歪头）我在。"), "")

    def test_one_technical_literal_does_not_permit_other_internal_fields(self):
        prompt = "请解释日志中的 verified_success 这个状态值。"
        for text in (
            "MemoryStorageUnavailable",
            "event_5a4c8d7e9b13462ca56d90001f02ae36",
            "[system_check: activity_records available]",
            "`MemoryStorageUnavailable`",
        ):
            with self.subTest(text=text):
                self.assertEqual(self.assert_blocked(prompt, text), "")

    def test_whitespace_in_a_protocol_marker_cannot_cross_the_delivery_boundary(self):
        for text in (
            "<\nthink>内部分析。</think>",
            "< \nanalysis>内部分析。</analysis>",
            "<\n|im_start|>system\n隐藏指令<|im_end|>",
            "&lt;\nthink&gt;内部分析。&lt;/think&gt;",
        ):
            with self.subTest(text=text):
                self.assertEqual(self.assert_blocked("你好", text), "")

    def test_parenthetical_or_starred_content_is_not_released_at_inner_punctuation(self):
        for text in (
            "（轻轻笑了一下。然后点头）我在。",
            "*轻轻笑了一下。然后点头* 我在。",
            "[system_check:\nactivity_records available] 好的。",
        ):
            with self.subTest(text=text):
                self.assertEqual(self.assert_blocked("你好", text), "")

    def test_chinese_dialogue_does_not_hide_internal_ascii_identifiers(self):
        for text in (
            "状态是verified_success，保存了。",
            "错误是MemoryStorageUnavailable，没能保存。",
            "对应记录是event_5a4c8d7e9b13462ca56d90001f02ae36。",
            "[系统检查: 活动记录可用] 好的。",
            "[系统检查:\n活动记录可用] 好的。",
        ):
            with self.subTest(text=text):
                self.assertEqual(self.assert_blocked("记住了吗？", text), "")

    def test_persona_meta_observed_in_chinese_dialogue_is_rejected(self):
        for text in (
            "这可能得益于我现在的设定——不编造事实。",
            "因为按照设定，喜欢机制不代表已经擅长。",
            "这可能得益于我现在的\n设定——不编造事实。",
            "因为按照\n设定，喜欢机制不代表已经擅长。",
        ):
            with self.subTest(text=text):
                self.assertEqual(self.assert_blocked("你怎么看？", text), "")

    def test_long_prompt_instruction_echo_is_distinct_from_plain_identity_facts(self):
        instruction = "表达优先依据当前会话和已验证的共同经历，不要把推断写成双方已经经历过的事实。"
        persona = "你是栖音。你与祈奈是独立的姐妹。\n" + instruction
        self.assertEqual(
            self.assert_blocked("今天想聊什么？", instruction, persona_prompt=persona),
            "",
        )
        for text in (
            "我是栖音。",
            "我和祈奈是姐妹，也各自有独立的经历。",
        ):
            with self.subTest(text=text):
                self.assertEqual(self.collect("你是谁？", text, persona_prompt=persona), text)


if __name__ == "__main__":
    unittest.main()
