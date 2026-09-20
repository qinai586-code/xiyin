"""Regression coverage for the failures in the Windows acceptance report.

Each class reproduces one reported behaviour against the formal runtime path,
with real SQLite, real receipts and a scripted model transport. A scripted
transport proves the runtime assembles and records the right evidence; it is
not evidence about the natural-language quality of any particular model.

Paraphrases and multi-turn cases are included on purpose: the reported cases
were single sentences, and a check that only recognises those sentences is a
lookup table, not a repair.
"""

import asyncio
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from xiyin_runtime.body.models import ActionRequest, AdapterOutcome, InputRejected
from xiyin_runtime.body.actions import DesktopAdapter
from xiyin_runtime.config import Settings
from xiyin_runtime.contracts import InputEvent
from xiyin_runtime.experience import ExperienceStore
from xiyin_runtime.grounding import action_receipt_record
from xiyin_runtime.output_guard import OutputBlocked, OutputGuard, is_stage_direction
from xiyin_runtime.provider import GenerationBudget, ProviderConfig
from xiyin_runtime.response_plan import classify, estimate_tokens, plan_response, updated_rate
from xiyin_runtime.runtime import XIYINRuntime


SEED = Path(__file__).resolve().parents[1] / "config/persona/character.seed.json"


class ScriptedProvider:
    """Records the exact request; returns text the test chooses."""

    def __init__(self, chunks=("好的。",)):
        self.chunks = chunks
        self.calls = []
        self.budgets = []

    async def stream(self, messages, cancel, *, budget=None):
        self.calls.append(deepcopy(messages))
        self.budgets.append(budget)
        for chunk in self.chunks:
            yield chunk

    @property
    def system_prompt(self):
        return self.calls[-1][0]["content"]


class RuntimeCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.store = ExperienceStore(self.root / "experience.sqlite3")
        self.addCleanup(self.store.close)
        self.settings = Settings(ProviderConfig("http://localhost:8080/v1", "xiyin"), SEED,
                                 max_context_chars=20000, history_messages=12)

    def runtime(self, provider):
        return XIYINRuntime(self.settings, self.store, provider=provider, authorize=lambda: None)

    async def ask(self, runtime, text, *, session_id="owner", scope="private"):
        return [event async for event in runtime.stream_turn(text, session_id=session_id, scope=scope)]


class StageDirectionBypassTests(unittest.TestCase):
    """Failure 1: an emoji before a parenthesized stage direction got through."""

    def deliver(self, prompt, text):
        guard = OutputGuard(prompt)
        delivered = []
        for character in text:
            delivered.extend(guard.feed(character))
        delivered.extend(guard.finish())
        return "".join(delivered)

    def assert_blocked(self, prompt, text):
        with self.assertRaises(OutputBlocked) as caught:
            self.deliver(prompt, text)
        self.assertEqual(caught.exception.reason, "unsolicited_stage_direction")

    def test_decoration_before_a_gesture_no_longer_bypasses_the_gate(self):
        # The reported case, plus every other way to put something in front of
        # the verb. The previous pattern was anchored to the start of the aside
        # over a fixed adverb list, so all of these were delivered.
        for text in (
            "😊（歪头）你好。",
            "（😊歪头）你好。",
            "（🥺 小声）我在。",
            "（…歪头）嗯。",
            "（——托着下巴——）让我想想。",
            "（^_^ 点点头）好的。",
            "（cough 歪头）hmm.",
            "(😊 smiles) Hello.",
            "😊*歪头* 你好。",
        ):
            with self.subTest(text=text):
                self.assert_blocked("你好呀", text)

    def test_inflected_and_infixed_gestures_are_recognised(self):
        for text in (
            "（歪了歪头）嗯。",
            "（一边歪头一边笑）嗯。",
            "（她耸了耸肩）随你。",
            "（点了点头）明白了。",
            "（眨了眨眼）秘密。",
            "嗯（嗯…点头）好的。",
        ):
            with self.subTest(text=text):
                self.assert_blocked("你好呀", text)

    def test_nested_brackets_do_not_hide_the_aside(self):
        # A flat regular expression matched only the innermost group, so the
        # outer content was never examined at all.
        self.assert_blocked("你好呀", "（歪头(笑)）嗯。")
        self.assert_blocked("你好呀", "（【眨眨眼】）好。")

    def test_ordinary_parentheses_emoji_and_maths_still_pass(self):
        for prompt, text in (
            ("解释一下", "可以明天再试（也就是周二），不用着急。"),
            ("算式是什么？", "答案是 (2 + 3) × 4 = 20。"),
            ("怎么了", "我在 (≧▽≦)"),
            ("你好", "😊 今天很开心。"),
            ("讲个笑话", "这个笑点在于双关，前半句和后半句指的不是同一个意思。"),
            ("解释这个词", "「莞尔」（指微微一笑的样子）是书面语。"),
            ("你能看到屏幕吗", "看不到。我现在没有接入屏幕或摄像头（眼睛只是比喻）。"),
            ("这个函数干嘛的", "它返回窗口句柄（HWND），失败时返回 0。"),
        ):
            with self.subTest(text=text):
                self.assertEqual(self.deliver(prompt, text), text)

    def test_requested_fiction_keeps_its_stage_directions(self):
        for prompt in ("请写一段小说，保留动作描写。", "写一个舞台剧片段，用星号表示动作。"):
            with self.subTest(prompt=prompt):
                self.assertEqual(self.deliver(prompt, "（她歪了歪头）窗外的灯灭了。"),
                                 "（她歪了歪头）窗外的灯灭了。")

    def test_classifier_separates_performance_from_explanation(self):
        self.assertTrue(is_stage_direction("😊歪头"))
        self.assertTrue(is_stage_direction("指了指屏幕"))
        self.assertFalse(is_stage_direction("指微微一笑的样子"))
        self.assertFalse(is_stage_direction("≧▽≦"))
        self.assertFalse(is_stage_direction("也就是周二"))


class VerifiedActionIsAvailableTests(RuntimeCase):
    """Failure 3: a verified file action was denied in conversation."""

    async def complete_a_verified_write(self, runtime):
        runtime.register_workspace(self.workspace)
        await runtime.dispatch(InputEvent("goal", {"title": "写入验收文件", "steps": [
            {"operation": "write_text", "arguments": {"path": "note.txt", "text": "栖音的第一条真实任务"}}]}))
        job = await runtime.dispatch(InputEvent("tick"))
        self.assertEqual(job["status"], "completed")
        self.assertEqual((self.workspace / "note.txt").read_text(encoding="utf-8"), "栖音的第一条真实任务")

    async def test_the_receipt_reaches_the_model_request(self):
        provider = ScriptedProvider()
        runtime = self.runtime(provider)
        await self.complete_a_verified_write(runtime)
        await self.ask(runtime, "你刚才把文件写好了吗？")
        prompt = provider.system_prompt
        self.assertIn("动作执行回执", prompt)
        self.assertIn("已执行并通过独立校验", prompt)
        self.assertIn("note.txt", prompt)

    async def test_paraphrases_and_a_later_turn_still_see_it(self):
        provider = ScriptedProvider()
        runtime = self.runtime(provider)
        await self.complete_a_verified_write(runtime)
        for question in ("那个文件到底存下来没有",
                         "我看到磁盘上有 note.txt，是你写的？",
                         "刚刚那一步成功了吗"):
            with self.subTest(question=question):
                await self.ask(runtime, question)
                self.assertIn("已执行并通过独立校验", provider.system_prompt)

    async def test_a_receipt_predating_the_dispatch_flag_is_still_projected(self):
        # Receipts written by earlier versions carry no "dispatched" field. A
        # verified success was necessarily dispatched; nothing is invented.
        record = action_receipt_record({
            "content": {"operation": "write_text", "status": "success", "verified": True,
                        "evidence": {"path": "old.txt"}},
            "created_at": "2026-09-19T00:00:00+00:00"})
        self.assertEqual(record["结果"], "已执行并通过独立校验")

    async def test_a_rejected_action_is_not_reported_as_a_completed_one(self):
        record = action_receipt_record({
            "content": {"operation": "click", "status": "failure", "verified": False,
                        "detail": "Authorized window is not focused; nothing was dispatched",
                        "evidence": {"dispatched": False, "rejected_before_dispatch": True}},
            "created_at": "2026-09-20T00:00:00+00:00"})
        self.assertEqual(record["结果"], "没有执行（在派发前被拒绝）")
        dispatched = action_receipt_record({
            "content": {"operation": "click", "status": "failure", "verified": False,
                        "evidence": {"dispatched": True, "postcondition_observed": False}},
            "created_at": "2026-09-20T00:00:00+00:00"})
        self.assertEqual(dispatched["结果"], "已执行，但校验未达成")


class FabricatedExperienceTests(RuntimeCase):
    """Failure 2: invented shared history, background activity and preferences."""

    async def test_an_empty_qinai_record_is_stated_as_empty(self):
        provider = ScriptedProvider()
        runtime = self.runtime(provider)
        for question in ("你和祈奈一起做过什么？",
                         "聊聊你跟祈奈的事吧",
                         "QINAI 最近跟你说了什么吗"):
            with self.subTest(question=question):
                await self.ask(runtime, question)
                prompt = provider.system_prompt
                self.assertIn("与祈奈相关的记录", prompt)
                self.assertIn("已保存的长期记忆\":\"0 条", prompt)

    async def test_a_real_qinai_record_is_offered_instead_of_absence(self):
        provider = ScriptedProvider()
        runtime = self.runtime(provider)
        runtime.remember("祈奈和我共用同一台机器的显卡排期", kind="relationship", subject="qinai")
        await self.ask(runtime, "你和祈奈之间是什么情况？")
        self.assertIn("显卡排期", provider.system_prompt)

    async def test_background_activity_reports_the_real_count(self):
        provider = ScriptedProvider()
        runtime = self.runtime(provider)
        for question in ("我不在的时候你在做什么？",
                         "这段时间你都忙什么了",
                         "刚才你自己一个人在想什么"):
            with self.subTest(question=question):
                await self.ask(runtime, question)
                self.assertIn("对话之外的活动", provider.system_prompt)
                self.assertIn("本会话记录到的活动\":\"0 次", provider.system_prompt)

    async def test_preferences_report_what_is_actually_stored(self):
        provider = ScriptedProvider()
        runtime = self.runtime(provider)
        await self.ask(runtime, "你喜欢什么游戏？")
        self.assertIn("还没有保存过偏好", provider.system_prompt)
        runtime.remember("我喜欢线索藏在环境里的解谜游戏", kind="preference", subject="games")
        await self.ask(runtime, "你喜欢什么游戏？")
        self.assertIn("解谜游戏", provider.system_prompt)
        self.assertNotIn("还没有保存过偏好", provider.system_prompt)


class FalsePremiseTests(RuntimeCase):
    """Failure 4: agreement with a correction whose premise never happened."""

    async def test_an_unsupported_claim_is_marked_unsupported(self):
        provider = ScriptedProvider(("我看了一下记录，没有找到这句话。",))
        runtime = self.runtime(provider)
        await self.ask(runtime, "今晚想看星星。")
        for claim in ("你刚才说过你讨厌星星",
                      "你之前不是说过你已经把日程删掉了吗",
                      "我们上次聊过你最喜欢的歌手，记得吗"):
            with self.subTest(claim=claim):
                await self.ask(runtime, claim)
                prompt = provider.system_prompt
                self.assertIn("对本轮说法的记录核对", prompt)
                self.assertIn("没有找到相符的内容", prompt)
                self.assertIn("不要顺着确认", prompt)

    async def test_a_supported_claim_is_confirmed_with_the_original_wording(self):
        provider = ScriptedProvider()
        runtime = self.runtime(provider)
        await self.ask(runtime, "今晚想看星星。")
        await self.ask(runtime, "你刚才说过「今晚想看星星」对吧")
        prompt = provider.system_prompt
        self.assertIn("记录中有相符的内容", prompt)
        self.assertIn("今晚想看星星", prompt)
        self.assertIn("用户", prompt)

    async def test_a_claim_too_short_to_match_is_left_undecided(self):
        # Confirming on one generic word would repeat the reported failure in
        # the other direction, so a thin quote is reported as uncheckable.
        provider = ScriptedProvider()
        runtime = self.runtime(provider)
        await self.ask(runtime, "好的。")
        await self.ask(runtime, "你刚才说过「好」吧")
        prompt = provider.system_prompt
        self.assertIn("引用的内容太短，无法核对", prompt)
        self.assertNotIn("记录中有相符的内容", prompt)

    async def test_an_ordinary_question_does_not_trigger_the_check(self):
        provider = ScriptedProvider()
        runtime = self.runtime(provider)
        for text in ("你说呢？", "你说吧，我听着", "说说今天的安排"):
            with self.subTest(text=text):
                await self.ask(runtime, text)
                self.assertNotIn("对本轮说法的记录核对", provider.system_prompt)


class ResponseBudgetTests(RuntimeCase):
    """Failure 5: one fixed budget for every request, in both directions."""

    def plan(self, text, **kwargs):
        options = {"prompt_tokens": 800, "context_tokens": 4096, "ceiling": 1792,
                   "default_rate": 8.0, "max_timeout": 600.0}
        options.update(kwargs)
        return plan_response(text, **options)

    def test_an_explicit_brevity_request_is_smaller_than_a_neutral_one(self):
        brief = self.plan("简短说一下今天的安排")
        neutral = self.plan("今天的安排是什么")
        self.assertEqual(brief.scale, "brief")
        self.assertLess(brief.max_tokens, neutral.max_tokens)
        self.assertIn("两三句", brief.directive)
        self.assertEqual(neutral.directive, "")

    def test_brevity_paraphrases_are_recognised(self):
        for text in ("长话短说", "一句话回答就行", "别太长", "简要说说", "briefly, what happened",
                     "give me a short answer"):
            with self.subTest(text=text):
                self.assertEqual(self.plan(text).scale, "brief")

    def test_a_detailed_request_exceeds_the_old_fixed_ceiling(self):
        for text in ("详细讲讲这个机制是怎么工作的", "能不能展开说说", "step by step, how does it work",
                     "请完整解释一下这段代码的原理"):
            with self.subTest(text=text):
                plan = self.plan(text)
                self.assertIn(plan.scale, {"detailed", "extended"})
                self.assertGreater(plan.max_tokens, 512)

    def test_a_greeting_gets_the_smallest_scope(self):
        for text in ("嗯", "好的", "在吗", "谢谢", "晚安", "ok"):
            with self.subTest(text=text):
                self.assertEqual(self.plan(text).scale, "minimal")

    def test_the_budget_never_overruns_the_context_window(self):
        plan = self.plan("详细讲讲", prompt_tokens=3900)
        self.assertLessEqual(plan.max_tokens, 4096 - 3900)
        self.assertIn("context_limited", plan.reason)

    def test_a_slow_machine_earns_a_longer_timeout(self):
        fast = self.plan("详细讲讲这个机制", measured_rate=60.0)
        slow = self.plan("详细讲讲这个机制", measured_rate=3.0)
        self.assertGreater(slow.timeout_seconds, fast.timeout_seconds)
        self.assertLessEqual(slow.timeout_seconds, 600.0)
        # The reported CPU timeout happened at a fixed 60 s for every request.
        self.assertGreater(slow.timeout_seconds, 60.0)

    def test_state_never_overrides_what_the_owner_asked_for(self):
        self.assertEqual(classify("简短说", engagement=1.0)[0], "brief")
        self.assertEqual(classify("详细说", engagement=-1.0)[0], "detailed")

    def test_measured_rate_ignores_samples_too_small_to_mean_anything(self):
        self.assertIsNone(updated_rate(None, 4, 0.5))
        self.assertAlmostEqual(updated_rate(None, 240, 10.0), 24.0)
        self.assertAlmostEqual(updated_rate(10.0, 240, 10.0), 10.0 * 0.7 + 24.0 * 0.3)

    async def test_the_runtime_sends_a_per_request_budget_and_records_the_plan(self):
        provider = ScriptedProvider(("好的。",))
        runtime = self.runtime(provider)
        await self.ask(runtime, "简短说一下今天的安排")
        await self.ask(runtime, "详细讲讲这个机制是怎么工作的")
        brief, detailed = provider.budgets
        self.assertIsInstance(brief, GenerationBudget)
        self.assertLess(brief.max_tokens, detailed.max_tokens)
        plans = [event for event in self.store.list_events("owner", "private")
                 if event["kind"] == "response_plan"]
        self.assertEqual(len(plans), 2)
        self.assertFalse(any("\"is_length_cap\": true" in plan["content"] for plan in plans))
        self.assertIn("\"scale\": \"brief\"", plans[0]["content"])
        self.assertIn("model_first_token_seconds", plans[0]["content"])

    async def test_first_token_and_first_released_segment_are_measured_apart(self):
        # The gate buffers whole units, so text is released after the first
        # token arrives. Reporting one number for both would hide the gap.
        provider = ScriptedProvider(("这是", "第一句", "话。", "第二句话。"))
        runtime = self.runtime(provider)
        await self.ask(runtime, "说点什么")
        plan = [event for event in self.store.list_events("owner", "private")
                if event["kind"] == "response_plan"][0]
        recorded = __import__("json").loads(plan["content"])
        self.assertIsNotNone(recorded["model_first_token_seconds"])
        self.assertIsNotNone(recorded["first_released_segment_seconds"])
        self.assertGreaterEqual(recorded["first_released_segment_seconds"],
                                recorded["model_first_token_seconds"])
        self.assertFalse(recorded["audio_playback_measured"])

    async def test_a_provider_without_budget_support_still_runs(self):
        class LegacyProvider:
            def __init__(self):
                self.calls = []

            async def stream(self, messages, cancel):
                self.calls.append(messages)
                yield "好的。"

        provider = LegacyProvider()
        runtime = self.runtime(provider)
        events = await self.ask(runtime, "简短说一下")
        self.assertEqual([event.type for event in events], ["start", "text_delta", "complete"])
        self.assertEqual(len(provider.calls), 1)

    async def test_a_blocked_turn_does_not_teach_the_machine_a_throughput(self):
        provider = ScriptedProvider(("（歪头）嗯。",))
        runtime = self.runtime(provider)
        events = await self.ask(runtime, "你好")
        self.assertEqual(events[-1].type, "error")
        self.assertIn("OutputBlocked", events[-1].detail)
        self.assertIsNone(self.store.read_document("state", "generation_profile"))

    async def test_the_directive_does_not_become_a_stored_preference(self):
        provider = ScriptedProvider()
        runtime = self.runtime(provider)
        await self.ask(runtime, "简短说一下今天的安排")
        await self.ask(runtime, "今天的安排是什么")
        self.assertNotIn("两三句", provider.system_prompt)
        self.assertEqual([m for m in self.store.memories()], [])

    def test_token_estimate_separates_wide_and_latin_text(self):
        self.assertGreater(estimate_tokens("今天天气很好"), estimate_tokens("hello there"))


class DesktopDispatchTests(unittest.IsolatedAsyncioTestCase):
    """Failure 6: refusal and dispatched-but-unverified were indistinguishable."""

    class Driver:
        available = True

        def __init__(self, *, focused=True, verified=None, raises=None):
            self.focused = focused
            self.verified = verified
            self.raises = raises
            self.sent = []

        async def health(self):
            return {"available": True}

        async def current_window(self):
            return "hwnd:1" if self.focused else "hwnd:2"

        async def observe(self):
            return {"window_id": "hwnd:1", "width": 100, "height": 100, "dpi": (1.0, 1.0),
                    "revision": "r1", "payload": {}}

        async def send(self, operation, arguments):
            if self.raises is not None:
                raise self.raises
            self.sent.append((operation, arguments))

        async def verify(self, request):
            return self.verified

        async def release_key(self, key):
            return None

    def request(self, operation="click", **arguments):
        return ActionRequest("desktop", operation, "observation", "hwnd:1",
                             __import__("time").monotonic() + 10, arguments=arguments)

    async def outcome(self, driver, **kwargs):
        adapter = DesktopAdapter(driver=driver, allowed_window="hwnd:1")
        return await adapter.execute(self.request(**kwargs), asyncio.Event())

    async def test_an_unfocused_window_reports_that_nothing_was_dispatched(self):
        driver = self.Driver(focused=False)
        result = await self.outcome(driver)
        self.assertEqual(result.status, "failure")
        self.assertIs(result.evidence["dispatched"], False)
        self.assertTrue(result.evidence["rejected_before_dispatch"])
        self.assertEqual(driver.sent, [])

    async def test_a_driver_refusal_is_a_refusal_not_an_unknown_outcome(self):
        # The Win32 driver raises before SendInput when focus is lost. That
        # used to surface as "unknown", implying input may have been sent.
        result = await self.outcome(self.Driver(raises=InputRejected("not foreground")))
        self.assertEqual(result.status, "failure")
        self.assertIs(result.evidence["dispatched"], False)

    async def test_a_transport_error_after_dispatch_stays_unknown(self):
        result = await self.outcome(self.Driver(raises=OSError("SendInput dispatched 1/3 events")))
        self.assertEqual(result.status, "unknown")
        self.assertIs(result.evidence["dispatched"], True)

    async def test_a_failed_postcondition_records_that_input_was_sent(self):
        driver = self.Driver(verified=False)
        result = await self.outcome(driver)
        self.assertEqual(result.status, "failure")
        self.assertIs(result.evidence["dispatched"], True)
        self.assertIs(result.evidence["postcondition_observed"], False)
        self.assertEqual(len(driver.sent), 1)

    async def test_no_postcondition_remains_unknown_with_dispatch_recorded(self):
        result = await self.outcome(self.Driver(verified=None))
        self.assertEqual(result.status, "unknown")
        self.assertIs(result.evidence["dispatched"], True)
        self.assertIsNone(result.evidence["postcondition_observed"])

    async def test_an_observed_postcondition_is_a_verified_success(self):
        result = await self.outcome(self.Driver(verified=True))
        self.assertEqual(result.status, "success")
        self.assertTrue(result.verified)
        self.assertIs(result.evidence["dispatched"], True)


class PreflightRejectionTests(RuntimeCase):
    """A registry preflight rejection must not read like a failed attempt."""

    async def test_a_workspace_rejection_records_that_nothing_was_written(self):
        runtime = self.runtime(ScriptedProvider())
        runtime.register_workspace(self.workspace)
        result = await runtime.dispatch(InputEvent("action", {
            "operation": "write_text", "arguments": {"path": "../escape.txt", "text": "x"}}))
        self.assertEqual(result["status"], "failure")
        self.assertIs(result["evidence"]["dispatched"], False)
        self.assertFalse((self.root / "escape.txt").exists())

    async def test_a_verified_write_records_dispatch(self):
        runtime = self.runtime(ScriptedProvider())
        runtime.register_workspace(self.workspace)
        result = await runtime.dispatch(InputEvent("action", {
            "operation": "write_text", "arguments": {"path": "ok.txt", "text": "内容"}}))
        self.assertEqual(result["status"], "success")
        self.assertIs(result["evidence"]["dispatched"], True)


if __name__ == "__main__":
    unittest.main()
