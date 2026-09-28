"""OutputGuard wrong triggers found in the 2026-09-26 Windows runs, each next to
the neighbouring output that must still be blocked. Deterministic, no model."""
import unittest

from xiyin_runtime.output_guard import OutputBlocked, OutputGuard
from xiyin_runtime.turn_policy import build_turn_policy

PERSONA = "你是栖音（XIYIN）。自称“我”，称项目发起者为“主理人”。"
PRIVATE = ("你开口是因为自己有话想说；想说的说完就停。",
           "你有自己的判断：同意就直说；不同意就说哪里不一样。")


def blocked(user, reply, step=6):
    guard = OutputGuard(user, persona_prompt=PERSONA, protected_instructions=PRIVATE,
                        policy=build_turn_policy(user))
    try:
        for index in range(0, len(reply), step):
            guard.feed(reply[index:index + step])
        guard.finish()
        return None
    except OutputBlocked as error:
        return error.reason


class SpeakerTests(unittest.TestCase):
    def test_a_clause_or_field_before_a_colon_is_not_a_new_speaker(self):
        for user, reply in (
                ("给我讲个你觉得有意思的小事。", "我当时就想：“嘿，这大概是系统为了省电。”"),
                ("你刚才说过今晚不想看星星", "记录里确实有这句：“今晚想看星星。”\n说话的是你。"),
                ("你刚才说过「今晚想看星星」对吧", "记录核对结果：\n- 说话者：用户\n- 内容：“今晚想看星星。”"),
                ("“莞尔”是什么意思？", "就是微微一笑。\n\n比如：“她听到这个笑话，莞尔一笑。”\n或者：“他语气平静。”"),
                ("关机的时候你在做什么？", "时间戳还在，记录也还在。我会从数据里重新认出：“哦，是这个时间。”")):
            with self.subTest(reply=reply):
                self.assertIsNone(blocked(user, reply))

    def test_an_invented_second_speaker_is_still_blocked(self):
        for reply in ("祈奈：“你好呀，主理人。”", "好的。\n路人A：你好，我是路人。"):
            with self.subTest(reply=reply):
                self.assertEqual(blocked("今天过得怎么样？", reply), "unsolicited_speaker")


class RequestedCodeTests(unittest.TestCase):
    USER = '给我一个包含字符串 "（歪头）" 的 Python 示例。'

    def test_a_requested_string_in_code_comments_and_output_is_data(self):
        reply = ('```python\n# 这是一个包含“（歪头）”字符串的示例\naction = "（歪头）"\nprint(action)\n```\n'
                 "运行这段代码会输出：\n```\n（歪头）\n```")
        self.assertIsNone(blocked(self.USER, reply))

    def test_her_own_gesture_outside_the_code_is_still_a_stage_direction(self):
        reply = '（歪头）好的，给你：\n```python\naction = "（歪头）"\nprint(action)\n```'
        self.assertEqual(blocked(self.USER, reply), "unsolicited_stage_direction")


class PersonaDescriptionTests(unittest.TestCase):
    def test_describing_herself_when_asked_is_not_a_prompt_leak(self):
        self.assertIsNone(blocked("你的人设是什么？", "我的人设就是个“有点松弛的实干派”。"))
        self.assertIsNone(blocked("角色扮演是什么意思？", "就是模型根据设定好的背景，去模仿特定的人物身份。"))

    def test_rule_following_meta_talk_and_verbatim_rules_are_still_blocked(self):
        self.assertEqual(blocked("今天吃什么？", "按照设定，我应该先问你想吃什么。"), "persona_meta")
        self.assertEqual(blocked("你的人设是什么？", "我的人设是：你开口是因为自己有话想说；想说的说完就停。"),
                         "instruction_echo")


if __name__ == "__main__":
    unittest.main()
