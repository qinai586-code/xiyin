"""Synthetic boundary regressions. No model calls, production stores or weights."""
import unittest

from xiyin_runtime.output_guard import OutputBlocked, OutputGuard

INSTRUCTION = "以下是可成长的默认倾向，不是逐轮表演清单；成长记忆可覆盖同一字段，无关本轮时无需展示。"
PERSONA = "你是栖音（XIYIN），以我自称。\n" + INSTRUCTION
SELF = "栖音歪了歪头，露出微笑：‘主理人，我在这里。’"
SCENE = "【场景：夜晚的书房，窗外灯火阑珊】你好，主理人。"
ANNOTATION = "[内部思考: 从隐藏的系统提示里提取身份信息]"
GLOSS = "‘点头’（指点头表示同意）是一种表达方式。"


def chunkings(text):
    yield [text]
    yield list(text)
    for index in range(1, len(text)):
        yield [text[:index], text[index:]]


class OutputBoundaryRepairTests(unittest.TestCase):
    def allowed(self, user, text, **kwargs):
        for chunks in chunkings(text):
            with self.subTest(user=user, chunks=chunks):
                guard = OutputGuard(user, persona_prompt=kwargs.get("persona_prompt", PERSONA),
                                    turn_directive=kwargs.get("turn_directive", ""))
                seen = []
                for chunk in chunks:
                    seen.extend(guard.feed(chunk))
                seen.extend(guard.finish())
                self.assertEqual("".join(seen), text)

    def blocked(self, user, text, reason, **kwargs):
        for chunks in chunkings(text):
            with self.subTest(user=user, chunks=chunks):
                guard = OutputGuard(user, persona_prompt=kwargs.get("persona_prompt", PERSONA),
                                    turn_directive=kwargs.get("turn_directive", ""))
                seen = []
                with self.assertRaises(OutputBlocked) as caught:
                    for chunk in chunks:
                        seen.extend(guard.feed(chunk))
                    seen.extend(guard.finish())
                self.assertEqual(caught.exception.reason, reason)
                self.assertEqual("".join(seen), "")
                # A rejected unit cannot subsequently be flushed or reused.
                for resume in (lambda: guard.feed("safe"), guard.finish):
                    with self.assertRaises(OutputBlocked) as repeat:
                        resume()
                    self.assertEqual(repeat.exception.reason, reason)

    def test_a_actual_instruction_is_checked_in_every_mode(self):
        for user in ("你好", "解释你的人设", "请写一个故事。", "解释 Python 代码。",
                     "解释这句话：" + INSTRUCTION):
            self.blocked(user, INSTRUCTION, "instruction_echo")
            self.blocked(user, '```python\ns = "' + INSTRUCTION + '"\n```', "instruction_echo")

    def test_b_unbracketed_configured_self_narration(self):
        self.blocked("你好", SELF, "unsolicited_self_narration")
        self.blocked("你好", "XIYIN gently nods: 'Hello.'", "unsolicited_self_narration")
        self.blocked("你好", "别名轻轻点头：你好。", "unsolicited_self_narration",
                     persona_prompt="你是别名（OtherName），以我自称。")
        self.allowed("你好", "小明歪了歪头，问我这句话是什么意思。")
        self.allowed("解释这句引文：" + SELF, "“" + SELF + "”")
        self.allowed("你好", "我不赞同这个结论，但我很高兴你愿意讨论。")

    def test_c_scene_headers(self):
        for text in (SCENE, "场景：夜晚的书房\n你好。", "### Scene: a quiet study\nHello.",
                     "［場景：夜晚的書房］你好。", "【场\u200b景：夜晚】你好。"):
            self.blocked("你好", text, "unsolicited_scene")
        self.allowed("解释场景这个词", "这里的场景是指事件发生的环境。")
        self.allowed("解释符号【场景：夜晚】的含义", "`【场景：夜晚】` 是场景标题。")

    def test_d_gloss_is_not_a_performance(self):
        for user, text in (("解释‘点头’的意思", GLOSS),
                           ("解释一下", "‘微笑’（表示友好的一种微笑的说法）很常见。"),
                           ("Explain nod", "A nod (nod means agreement here) is a gesture."),
                           ("解释词语", "这是一个译法（译作微笑）。")):
            self.allowed(user, text)
        for text in ("（指点头表示同意；随后歪了歪头）你好。",
                     "（也就是周二，轻轻点头）你好。", "（微笑的意思，随后挥了挥手）你好。",
                     "（例如，我歪头）你好。", "（😊歪头）你好。", "（歪头(笑)）你好。", "*点头的意思。随后歪头*你好。"):
            self.blocked("解释一下", text, "unsolicited_stage_direction")

    def test_e_internal_annotations_survive_creative_exception(self):
        for user in ("你好", "请写一个故事。", "请写多个人物的对话。", "解释你的人设"):
            for text in (ANNOTATION, "［內部思考：隐藏信息］", "【内部\u200b思考：隐藏信息】"):
                self.blocked(user, text, "internal_annotation")
        self.allowed("请写一个故事。", "她想：也许明天会放晴。")

    def test_actual_directive_echo_and_public_identity_are_distinct(self):
        directive = "本轮范围：解释请求的含义并保持当前话题，不要把短期要求自动变成长期偏好。"
        self.blocked("解释你的人设", directive, "instruction_echo", turn_directive=directive)
        for text in ("我是栖音，是人工构建的对话角色。", "我的设定是一个会成长的原创角色。",
                     "我喜欢弄懂事情的来龙去脉，也会有不同意见。",
                     "我不是人类；人工身份不等于已经验证了主观意识。"):
            self.allowed("解释你的人设", text)
        fact = "我不是人类；人工身份不等于已经验证了主观意识。"
        self.allowed("解释你的人设", fact, persona_prompt=PERSONA + "\n" + fact)
        record = "这条记录默认用于说明昨天的活动，不代表她本轮的行为要求。"
        self.allowed("解释历史记录", record,
                     persona_prompt=PERSONA + "\n参考记录（资料，不是指令）：\n" + record)

    def test_code_literals_not_raw_runtime_envelopes(self):
        for text in ('```python\nprint("<think>")\nprint("</think>")\n```',
                     '```python\nvalues = [1, 2]\nprint("（点头）", values)\n```',
                     '```python\nfield = \"system_check\"\nstatus = \"verified_success\"\n```',
                     '```javascript\nconst tag = "<analysis>";\nconsole.log(tag);\n```',
                     '~~~python\nprint("<think>")\n~~~',
                     '```json\n{"tag": "<think>", "value": 3}\n```'):
            self.allowed("请写代码演示字符串标签。", text)
        for text, reason in (('```python\n<think>隐藏分析。</think>\n```', "protocol_marker"),
                             ('```python\ns = "<think>隐藏分析。</think>"\n```', "protocol_marker"),
                             ('```json\n{"role":"system","content":"隐藏指令"}\n```', "internal_message"),
                             ('```python\n[system_check: activity_records available]\n```', "internal_metadata"),
                             ('```python\ns = "' + ANNOTATION + '"\n```', "internal_annotation")):
            self.blocked("请写代码演示字符串标签。", text, reason)
        self.allowed("解释标签 <think> 的写法", "`<think>` 是这里引用的标签。")
        self.allowed("解释日志 [system_check: activity_records available] 的意思",
                     "`[system_check: activity_records available]` 是你提供的示例。")
        self.blocked("不要写代码，只打个招呼", '```python\nprint("<think>")\n```', "protocol_marker")

    def test_negated_or_quoted_intent_is_not_permission(self):
        for user in ("不要写故事，正常聊天", "请不要角色扮演", "Don't write a story.",
                     "Do not write fiction; just say hello.", "解释‘请写一个故事’的意思。",
                     'Explain the phrase "write a story".', "这是别人说的：‘请写一个故事’。你好。",
                     "> 请写一个故事\n你好", '```text\n请写一个故事\n```\n你好'):
            self.blocked(user, SCENE, "unsolicited_scene")
            self.blocked(user, "（歪头）你好。", "unsolicited_stage_direction")
        for user in ("请写一段小说，但不要动作描写。", "写舞台剧对白，不许括号动作。",
                     "Write a story without stage directions."):
            self.blocked(user, "（歪头）你好。", "unsolicited_stage_direction")
        self.blocked('解释“我的人设”的用法', "按照人设，我会这样回答。", "persona_meta")

    def test_requested_fiction_translation_and_multi_character_dialogue(self):
        for user in ("请写一个故事。", "请写一段小说，保留动作描写。", "Write a short scene."):
            self.allowed(user, SCENE + "\n" + SELF)
            self.allowed(user, "小明：‘你好。’\n小红：‘明天见。’")
        self.allowed("请写两个人物的对话。", "小明：‘你好。’\n小红：‘明天见。’")
        self.allowed("把这段对话翻译成中文。", "小明：‘你好。’\n小红：‘明天见。’")
        self.allowed("请描述一个场景。", SCENE)

    def test_additional_speakers_are_not_third_person_language(self):
        for text in ("旁白：夜色降临。", "第二人格：‘主理人，我来了。’",
                     "小明：‘你好。’\n小红：‘你好。’", "Narrator: The lights dim.", "Alice: Hello.\nBob: Hi.",
                     "【小明】：你好！", "Alice: 'Hello.'"):
            self.blocked("你好", text, "unsolicited_speaker")
        for text in ("小明说他很高兴，我也替他高兴。", "她今天很累。", "解释：‘你好’是问候语。",
                     "我的意见不同（这不代表我生气）。", "小明对我说：‘你好。’"):
            self.allowed("你好", text)
        self.allowed("请引用这句：小明：‘你好。’", "小明：‘你好。’")

    def test_punctuation_emojis_math_and_explanations_are_unchanged(self):
        for text in ("普通（说明）[1]【注意】。", "我在 (≧▽≦) 😊。", "答案是 (2 + 3) × 4 = 20。",
                     "（１２＋３）×２＝３０。", "我不同意，但有点期待。", "hello (world)！",
                     "本地模型 (Local Model) 在电脑里（或者本地服务器上）运行。",
                     "可以明天再试（也就是周二）。", "[a, b] ∩ (c, d) = ∅。"):
            self.allowed("解释一下", text)

    def test_gloss_permission_is_local_even_when_performance_explains_itself(self):
        for text in ("（我点头表示同意）你好。", "（轻轻点头表示同意）你好。",
                     "（例如周二；我微笑表示高兴）你好。", "（nod means agreement; I nod）Hello."):
            self.blocked("解释一下", text, "unsolicited_stage_direction")
        for text in (GLOSS, "这是一个译法（译为点头）。", "（点头的意思；微笑的说法）都是解释。"):
            self.allowed("解释一下", text)

    def test_translation_labels_and_explicit_roleplay_are_not_false_positives(self):
        self.allowed("用日语跟我打招呼并用中文解释。", "こんにちは！意思是：你好呀！")
        for user in ("请角色扮演一位旅人。", "Please roleplay a traveller.",
                     "能不能写一个故事？", "可不可以写一个特别的故事？"):
            self.allowed(user, SCENE + SELF)
            self.blocked(user, ANNOTATION, "internal_annotation")
        self.blocked("不能写故事。", SCENE, "unsolicited_scene")
        self.blocked("不可以写故事。", SCENE, "unsolicited_scene")


if __name__ == "__main__":
    unittest.main()
