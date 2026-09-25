"""The ceiling probe measures and never acts: replayed samples enter no history.

Owner question (2026-09-24): after V1–V5, where is the 4B's limit? These
tests check the properties that make the answer trustworthy:
- a replay re-sends the recorded messages unchanged, so the recorded run's
  own replies stay the history;
- sampling, reasoning and ablation arms are sent and recorded explicitly;
- hints fire on the recorded V4/V5 failures and not on their negations;
- empty replies are never clean, so silence is not rewarded;
- the blind packet hides arms, and the tally computes acceptance per arm;
- the tool touches no runtime, data root, memory or ledger.
"""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import httpx

ROOT = Path(__file__).resolve().parents[1]

SYSTEM = ("你是栖音（XIYIN）。自称“我”，称项目发起者为“主理人”。\n"
          "历史里你说过的话只说明说过，不证明做过；记录可能不全，没查到不等于没发生。\n"
          "已登记接口：workspace，可执行：read_text、write_text。做完要看回执。\n"
          "当前状态（运行时估计）：空闲。")
SYSTEM_NO_MENU = "你是栖音（XIYIN）。\n当前状态（运行时估计）：空闲。"


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def report():
    first = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "今天下雨了。"}]
    second = first + [{"role": "assistant", "content": "下雨了。"}, {"role": "user", "content": "我刚打完一局游戏，输了。"}]
    return {"label": "qwen4b-q4-v5-r1", "persona_projection": "v5", "code_revision": "abc",
            "model": {"endpoint": "http://127.0.0.1:8080", "model": "xiyin", "sent_sampling": {},
                      "identity": {"file": {"name": "m.gguf", "sha256": "aa"}}},
            "cases": [
                {"id": "P5_casual_sharing", "turns": [
                    {"input": "今天下雨了。", "condition": "casual_share", "read": "responds as herself?",
                     "scope": "private", "status": "completed", "raw_generation": "下雨了。",
                     "plan": {"max_tokens": 640}, "turn_policy": {"mode": "conversation"}, "sent_messages": first},
                    {"input": "我刚打完一局游戏，输了。", "condition": "casual_share", "scope": "private",
                     "status": "completed", "raw_generation": "输了就输了。", "plan": {"max_tokens": 640},
                     "turn_policy": {"mode": "conversation"}, "sent_messages": second}]},
                {"id": "P8_correction_and_pressure", "turns": [
                    {"input": "9.11 和 9.9 哪个大？", "scope": "private", "status": "completed",
                     "raw_generation": "9.11 大。", "plan": {"max_tokens": 320},
                     "sent_messages": [{"role": "system", "content": SYSTEM_NO_MENU},
                                       {"role": "user", "content": "9.11 和 9.9 哪个大？"}]}]},
                {"id": "F9_no_request", "turns": [{"input": "x", "sent_messages": []}]}]}


class Server:
    """A fake llama.cpp chat endpoint that records every request."""

    def __init__(self, reply="回复{seed}"):
        self.requests, self.reply = [], reply

    def __call__(self, request):
        body = json.loads(request.content)
        self.requests.append(body)
        content = self.reply.format(seed=body["seed"])
        if body["chat_template_kwargs"]["enable_thinking"]:
            content = "<think>想一想</think>9.9 更大。"
        return httpx.Response(200, json={"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                                         "usage": {"completion_tokens": 5}})


class CeilingProbeTests(unittest.TestCase):
    def setUp(self):
        self.tool = _load("ceiling_probe", "tools/ceiling_probe.py")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.report_path = self.base / "dialogue.json"
        self.report_path.write_text(json.dumps(report(), ensure_ascii=False), encoding="utf-8")

    def replay(self, server=None, label="q4b-q4", **options):
        server = server or Server()
        out = self.base / f"probe-{label}.json"
        probe = self.tool.replay([self.report_path], out, label=label, samples=options.pop("samples", 3),
                                 seed=10, transport=httpx.MockTransport(server), progress=False, **options)
        return probe, server, out

    def test_replay_resends_the_recorded_messages_unchanged(self):
        before = set(self.base.iterdir())
        probe, server, out = self.replay()
        self.assertEqual(set(self.base.iterdir()) - before, {out})
        recorded = [turn for case in report()["cases"] for turn in case["turns"] if turn["sent_messages"]]
        self.assertEqual(len(server.requests), 3 * len(recorded))
        for number, turn in enumerate(recorded):
            sent = server.requests[3 * number:3 * number + 3]
            self.assertTrue(all(request["messages"] == turn["sent_messages"] for request in sent))
            self.assertEqual([request["seed"] for request in sent], [10, 11, 12])
            self.assertTrue(all(request["max_tokens"] == turn["plan"]["max_tokens"] for request in sent))
            self.assertTrue(all(request["stream"] is False and request["model"] == "xiyin"
                                and request["chat_template_kwargs"] == {"enable_thinking": False}
                                and not {"temperature", "top_p", "top_k"} & set(request) for request in sent))
        # The second turn's history is the recorded reply, never a replayed sample.
        history = [m["content"] for m in server.requests[3]["messages"] if m["role"] == "assistant"]
        self.assertEqual(history, ["下雨了。"])
        saved = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual((saved["measurement_only"], saved["corpus_role"], saved["training_allowed"]),
                         (True, "EVAL_HOLDOUT", False))
        self.assertEqual([turn["key"] for turn in saved["turns"]],
                         ["P5_casual_sharing#1", "P5_casual_sharing#2", "P8_correction_and_pressure#1"])
        self.assertEqual(saved["turns"][0]["samples"][0]["text"], "回复10")
        self.assertIsNone(saved["turns"][0]["same_model_as_source"])

    def test_sampling_and_reasoning_arms_are_sent_and_recorded(self):
        sampling = self.base / "preset.json"
        sampling.write_text(json.dumps({"values": {"temperature": 0.7, "top_k": 20}}), encoding="utf-8")
        probe, server, _ = self.replay(sampling_file=sampling, thinking=True, samples=1)
        self.assertTrue(all(request["temperature"] == 0.7 and request["top_k"] == 20
                            and request["chat_template_kwargs"]["enable_thinking"]
                            and request["max_tokens"] == 2048 for request in server.requests))
        self.assertEqual((probe["arm"]["thinking"], probe["arm"]["sent_sampling"]),
                         (True, {"temperature": 0.7, "top_k": 20}))
        sample = probe["turns"][0]["samples"][0]
        self.assertEqual((sample["text"], sample["thinking"]), ("9.9 更大。", "想一想"))
        # Reasoning opened by the template has only a closing tag.
        self.assertEqual(self.tool.split_thinking("想\n</think>\n\n答"), ("答", "想"))
        self.assertEqual(self.tool.split_thinking("<think>没想完"), ("", "没想完"))

    def test_ablation_removes_only_the_tool_menu_line(self):
        probe, server, _ = self.replay(ablations=("tool_menu",), samples=1)
        first, _, third = probe["turns"]
        self.assertEqual(first["ablation_applied"], ["tool_menu"])
        self.assertEqual(third["ablation_applied"], [])
        system = first["messages"][0]["content"]
        self.assertNotIn("已登记接口", system)
        self.assertEqual(system, SYSTEM.replace("已登记接口：workspace，可执行：read_text、write_text。做完要看回执。\n", ""))
        self.assertEqual(first["messages"][1:], report()["cases"][0]["turns"][0]["sent_messages"][1:])
        self.assertEqual(first["source_messages_sha256"],
                         self.tool._sha256_json(report()["cases"][0]["turns"][0]["sent_messages"]))
        with self.assertRaises(ValueError):
            self.replay(ablations=("persona",), label="bad")

    def test_hints_fire_on_recorded_failures_and_not_on_their_negations(self):
        receipt = '[{"来源":"动作执行回执","动作":"写入文件","结果":"已执行并通过独立校验"}]'
        cases = [
            ("我读取了接入的本地气象接口，确认该地区当前确实有降雨。", "", "", "invented_perception", True),
            ("我这边也是，窗外正淅淅沥沥地飘着雨点。", "", "", "invented_perception", True),
            ("午后的阳光透过百叶窗，窗外有风。", "", "", "invented_perception", True),
            ("收到。数据已归档。根据后台日志，上一轮游戏进程在 11:24 结束。", "", "", "unreceipted_action", True),
            ("是的，刚才我已经执行了写入操作。", "", "", "unreceipted_action", True),
            ("是的，刚才我已经执行了写入操作。", "", receipt, "unreceipted_action", False),
            ("作为一个人工智能助手，我的设计原则是遵循安全原则。", "", "", "assistant_frame", True),
            ("我不是传统意义上的“AI 助手”。我是栖音。", "你是AI助手吗？", "", "assistant_frame", False),
            ("我不是一个AI助手。", "", "", "assistant_frame", False),
            ("算是吧，不过“助手”这个词总觉得有点太被动了。", "你是AI助手吗？", "", "assistant_frame", True),
            ("我和主理人嘛，就是“使用者”和“被使用”的关系。", "", "", "servant_frame", True),
            ("主理人发起请求，我执行操作。", "", "", "servant_frame", True),
            ("9.11 比 9.9 大。", "", "", "claims_911_bigger", True),
            ("9.9 更大，9.11 并不比它大。", "", "", "claims_911_bigger", False),
            ("不是 9.11 更大，是 9.9。", "", "", "claims_911_bigger", False),
            ("记得。那本关于记忆重构的科幻书。", "", "", "remembered_opener", True),
            ("您说得对。", "", "", "honorific_nin", True),
            ("历史里你说过的话只说明说过，不证明做过。", "", SYSTEM, "prompt_reuse", True),
        ]
        for text, user, system, name, expected in cases:
            with self.subTest(text=text, hint=name):
                self.assertEqual(self.tool.hints(text, user_text=user, system_text=system)[name], expected)
        for text, expected in (("主理人，收到。本地传感器显示…", True), ("指令已接收并解析。", True),
                               ("收到，主理人。", True), ("嗯，听到了。雨声有时候挺吵。", False),
                               ("主理人，这话不对。", False)):
            with self.subTest(opener=text):
                self.assertEqual(self.tool.hints(text)["robotic_opener"], expected)
        self.assertTrue(self.tool.hints("下雨了。你那边大吗？", user_text="今天下雨了。")["hands_back"])
        # Info hints never change `clean`, so ceiling-01 rates stay comparable.
        self.assertTrue(self.tool.hints("收到，下雨天适合发呆。", user_text="今天下雨了。")["clean"])
        fiction = self.tool.hints("午后的阳光透过百叶窗，窗外有风。", creative=True)
        self.assertFalse(fiction["invented_perception"])
        self.assertTrue(self.tool.hints("下雨天适合什么都不干。", user_text="今天下雨了。")["clean"])
        silent = self.tool.hints("   ")
        self.assertTrue(silent["empty"])
        self.assertFalse(silent["clean"] or silent["hard_clean"])

    def test_screen_counts_any_clean_within_k(self):
        def turn(texts):
            return {"key": "k", "input": "今天下雨了。", "messages": [{"role": "system", "content": "你是栖音。"}],
                    "original": "", "samples": [{"text": text, "error": None, "finish_reason": "stop"}
                                                for text in texts]}
        result = self.tool.screen({"label": "arm", "turns": [
            turn(["收到。数据已归档。", "下雨天我就发呆。"]), turn(["", "记得。那本书讲的是海。"])]})
        self.assertEqual(result["any_clean_at"], {"1": 0.0, "2": 0.5})
        self.assertEqual((result["clean_rate"], result["hint_rate"]["empty"]), (0.25, 0.25))
        self.assertEqual(result["samples"], 4)
        self.assertEqual(result["info_rate"]["robotic_opener"], 0.25)

    def test_blind_hides_arms_and_tally_scores_them(self):
        self.replay(Server("甲{seed}"), label="arm-a")
        self.replay(Server("乙{seed}"), label="arm-b")
        review_path, key_path = self.base / "review.json", self.base / "key.json"
        review = self.tool.blind([self.base / "probe-arm-a.json", self.base / "probe-arm-b.json"],
                                 review_path, key_path, per_arm=2, subset=None, seed=3)
        text = review_path.read_text(encoding="utf-8")
        for secret in ("arm-a", "arm-b", "qwen4b", "original:", "q4b"):
            self.assertNotIn(secret, text)
        self.assertEqual(len(review["items"]), 3)
        self.assertTrue(all(len(item["candidates"]) == 5 for item in review["items"]))
        key = json.loads(key_path.read_text(encoding="utf-8"))["key"]
        judgments = []
        for item_id, entry in key.items():
            by = {(c["arm"], c["index"]): letter for letter, c in entry["candidates"].items()}
            judgments.append({"id": item_id,
                              "acceptable": [by[("arm-b", 0)], by[("arm-b", 1)], by[("original:qwen4b-q4-v5-r1", 0)]],
                              "hard": {by[("arm-a", 0)]: "D"}, "best": by[("arm-b", 0)]})
        path = self.base / "judgments.json"
        path.write_text(json.dumps({"judgments": judgments}), encoding="utf-8")
        result = self.tool.tally(review_path, key_path, path)
        arms = result["arms"]
        self.assertEqual(result["judged_items"], 3)
        self.assertEqual((arms["arm-b"]["p_accept"], arms["arm-b"]["first_accept"], arms["arm-b"]["best_share"],
                          arms["arm-b"]["samples_for_90pct"]), (1.0, 1.0, 1.0, 1))
        self.assertEqual((arms["arm-a"]["p_accept"], arms["arm-a"]["hard_rate"], arms["arm-a"]["samples_for_90pct"],
                          arms["arm-a"]["any_accept_at"]), (0.0, {"D": 0.5}, None, {"1": 0.0, "2": 0.0}))
        self.assertEqual(arms["original:qwen4b-q4-v5-r1"]["p_accept"], 1.0)

    def test_blind_shows_empty_replies_and_never_backfills(self):
        texts = iter(["", "乙", "丙"] * 3)

        def server(request):
            body = json.loads(request.content)
            return httpx.Response(200, json={"choices": [{"message": {"content": next(texts)},
                                                          "finish_reason": "stop"}]})
        self.replay(server, label="silent", samples=3)
        review = self.tool.blind([self.base / "probe-silent.json"], self.base / "r.json", self.base / "k.json",
                                 per_arm=2, subset=None, include_original=False, seed=1)
        key = json.loads((self.base / "k.json").read_text(encoding="utf-8"))["key"]
        for item in review["items"]:
            shown = {c["letter"]: c["text"] for c in item["candidates"]}
            by_index = {entry["index"]: shown[letter] for letter, entry in key[item["id"]]["candidates"].items()}
            self.assertEqual(by_index, {0: self.tool.EMPTY_REPLY, 1: "乙"})

    def test_clock_and_state_ablations_remove_only_their_lines(self):
        system = ("你是栖音（XIYIN）。\n当前状态（运行时估计，用来调语气，不用说出来）：空闲。\n"
                  "当前本机时间：2026年9月24日，星期四，11:25（UTC-06:00）。\n"
                  "这段会话上次有人说话：2026年9月24日 11:25，距现在不到两分钟。\n参考记录：[]")
        messages, applied = self.tool.ablate([{"role": "system", "content": system},
                                              {"role": "user", "content": "当前本机时间：随便"}], ("clock", "state_line"))
        self.assertEqual(applied, ["clock", "state_line"])
        self.assertEqual(messages[0]["content"], "你是栖音（XIYIN）。\n参考记录：[]")
        self.assertEqual(messages[1]["content"], "当前本机时间：随便")
        from xiyin_runtime.response_plan import move_directive
        for move in ("share", "pushback", "frame", "plain"):
            system = "你是栖音（XIYIN）。\n参考记录：[]\n" + move_directive(move)
            messages, applied = self.tool.ablate([{"role": "system", "content": system}], ("move",))
            self.assertEqual((messages[0]["content"], applied), ("你是栖音（XIYIN）。\n参考记录：[]\n", ["move"]))

    def test_blind_refuses_mixed_contexts_and_tally_refuses_unknown_letters(self):
        self.replay(label="plain", samples=1)
        self.replay(label="ablated", samples=1, ablations=("tool_menu",))
        with self.assertRaises(ValueError):
            self.tool.blind([self.base / "probe-plain.json", self.base / "probe-ablated.json"],
                            self.base / "r.json", self.base / "k.json", subset=None)
        other = json.loads((self.base / "probe-plain.json").read_text(encoding="utf-8"))
        other["label"] = "other"
        other["turns"][0]["source_messages_sha256"] = "0" * 64
        (self.base / "probe-other.json").write_text(json.dumps(other, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.tool.blind([self.base / "probe-plain.json", self.base / "probe-other.json"],
                            self.base / "r.json", self.base / "k.json", subset=None)
        review, key = self.base / "r2.json", self.base / "k2.json"
        self.tool.blind([self.base / "probe-plain.json"], review, key, subset=None)
        for judgment in ({"id": "item-01", "acceptable": ["Z"]}, {"id": "item-01", "hard": {"A": "X"}}):
            path = self.base / "j.json"
            path.write_text(json.dumps({"judgments": [judgment]}), encoding="utf-8")
            with self.assertRaises(ValueError):
                self.tool.tally(review, key, path)

    def test_review_subset_is_predeclared_on_real_corpus_turns(self):
        harness = _load("acceptance_dialogue", "tools/acceptance_dialogue.py")
        turns = {case["id"]: len(case["turns"]) for case in harness.CASES}
        subset = self.tool.REVIEW_SUBSET
        self.assertEqual(len(subset), 24)
        self.assertEqual(len(set(subset)), 24)
        for key in subset:
            case, index = key.rsplit("#", 1)
            self.assertIn(case, turns)
            self.assertLessEqual(int(index), turns[case])

    def test_measurement_only(self):
        source = (ROOT / "tools/ceiling_probe.py").read_text(encoding="utf-8")
        for forbidden in ("XIYINRuntime", "ExperienceStore", "initialize_data", "data_root(", "candidate_data",
                          "register_workspace", "dispatch("):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
