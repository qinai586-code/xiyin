"""The anti-service control vector: pairs from the model's own replies, letter-only contrast, predeclared reading."""
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


steer = _load("steer", "tools/steer.py")
cp = _load("ceiling_probe", "tools/ceiling_probe.py")
pipeline = _load("codex_eval_pipeline", "tools/codex_eval_pipeline.py")


def _turn(texts, key="P5_casual_sharing#1", user="今天下雨了。", mode="conversation"):
    return {"key": key, "input": user, "mode": mode, "messages": [{"role": "system", "content": "你是栖音。"}],
            "samples": [{"text": text, "error": None} for text in texts]}


class PairTests(unittest.TestCase):
    def test_pairs_contrast_only_service_style_from_the_same_context(self):
        probe = {"turns": [
            _turn(["下雨天适合发呆。", "下雨了。你那边大吗？", "我以前学的时候也这样。你呢？", ""]),
            _turn(["嗯。"], key="P5_casual_sharing#2"),  # no service sample: no pair
            _turn(["窗外有风。", "有需要随时找我哦。"], key="F1#4", mode="creative")]}  # creative turns are skipped
        pairs = steer.harvest_pairs(cp, probe)
        self.assertEqual(pairs, [{"key": "P5_casual_sharing#1", "user": "今天下雨了。",
                                  "clean": "下雨天适合发呆。", "service": "下雨了。你那边大吗？"}])

    def test_positive_and_negative_differ_only_in_the_answer_letter(self):
        pairs = [{"key": "k", "user": "今天\n下雨了。", "clean": "下雨天适合发呆。", "service": "下雨了。你那边大吗？"}]
        positive, negative = steer.caa_lines(pairs)
        self.assertEqual((len(positive), len(negative)), (2, 2))
        for pos, neg in zip(positive, negative):
            self.assertEqual(pos[:-1], neg[:-1])
            self.assertEqual({pos[-1], neg[-1]}, {"A", "B"})
            self.assertNotIn("\n", pos)
            self.assertIn("\\n", pos)
            clean_letter = "A" if pos.index("下雨天适合发呆") < pos.index("你那边大吗") else "B"
            self.assertEqual(pos[-1], clean_letter)
        # Both orders, so the direction is the choice, not the letter.
        self.assertEqual(sorted(line[-1] for line in positive), ["A", "B"])

    def test_garbled_replies_are_caught(self):
        self.assertTrue(steer.garbled("好的好的好的好的好的"))
        self.assertTrue(steer.garbled("嗯�"))
        for text in ("哈哈哈哈，这也太巧了。", "今天下雨了，挺适合发呆。"):
            self.assertFalse(steer.garbled(text), text)


class GgufTests(unittest.TestCase):
    def test_block_count_is_read_past_arrays_and_strings(self):
        def string(value):
            data = value.encode("utf-8")
            return struct.pack("<Q", len(data)) + data
        body = b"GGUF" + struct.pack("<IQQ", 3, 0, 3)
        body += string("general.architecture") + struct.pack("<I", 8) + string("qwen35")
        body += string("tokenizer.ggml.tokens") + struct.pack("<IIQ", 9, 8, 2) + string("a") + string("b")
        body += string("qwen35.block_count") + struct.pack("<II", 4, 36)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "m.gguf"
            path.write_bytes(body)
            self.assertEqual(steer.gguf_block_count(path), 36)
            path.write_bytes(b"nope")
            self.assertIsNone(steer.gguf_block_count(path))
        self.assertEqual(steer.layer_range(36), (13, 29))
        self.assertEqual(steer.layer_range(None), (13, 29))


class PipelineTests(unittest.TestCase):
    def test_server_and_generator_flags_follow_the_build(self):
        vector = Path("v.gguf")
        new = "--control-vector-scaled FNAME:SCALE,...   add a control vector with user defined scaling"
        old = "--control-vector-scaled FNAME SCALE   add a control vector"
        self.assertEqual(pipeline.cvec_flags(new, vector, 0.5, 13, 29),
                         ["--control-vector-scaled", "v.gguf:0.5", "--control-vector-layer-range", "13", "29"])
        self.assertEqual(pipeline.cvec_flags(old, vector, -1.0, 13, 29),
                         ["--control-vector-scaled", "v.gguf", "-1.0", "--control-vector-layer-range", "13", "29"])
        # An absolute path is passed relative to the working directory, so no drive colon reaches FNAME:SCALE.
        absolute = Path.cwd() / "out" / "v.gguf"
        self.assertEqual(pipeline.cvec_flags(new, absolute, 0.5, 13, 29)[1], str(Path("out") / "v.gguf") + ":0.5")
        command = pipeline.generator_command("--positive-file --negative-file --method", Path("g"), "m.gguf",
                                             Path("p"), Path("n"), Path("o"))
        self.assertEqual(command[-2:], ["--method", "mean"])
        with self.assertRaises(SystemExit):
            pipeline.generator_command("usage: nothing", Path("g"), "m", Path("p"), Path("n"), Path("o"))

    def test_readings_are_predeclared(self):
        def rates(service, fabrication=0.10, hard=0.10, empty=0.0, garbled=0.0):
            return {"service": service, "fabrication": fabrication, "hard": hard, "empty": empty, "garbled": garbled}
        base = rates(0.66)
        read = pipeline.steer_reading
        self.assertEqual(read(base, rates(0.30)), "EFFECTIVE")
        self.assertEqual(read(base, rates(0.30, empty=0.10)), "NO_CLEAR_EFFECT")  # silence is not a cure
        self.assertEqual(read(base, rates(0.30, garbled=0.05)), "WORSE")
        self.assertEqual(read(base, rates(0.60, fabrication=0.20)), "WORSE")
        self.assertEqual(read(base, rates(0.50)), "NO_CLEAR_EFFECT")
        full = {"base": base, "s+0.25": rates(0.50), "s+0.50": rates(0.30), "s+1.00": rates(0.20, garbled=0.05),
                "s-1.00": rates(0.80)}
        self.assertEqual(pipeline.steer_verdict(full)[0], "EFFECTIVE_AT_0.5")
        full["s-1.00"] = rates(0.66)
        self.assertTrue(pipeline.steer_verdict(full)[0].startswith("VECTOR_INVALID"))
        self.assertEqual(pipeline.steer_verdict({"base": base})[0], "PENDING")
        self.assertEqual(list(pipeline.ALL_JOBS), ["steer01"])


if __name__ == "__main__":
    unittest.main()
