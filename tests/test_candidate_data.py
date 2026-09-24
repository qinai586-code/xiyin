"""Local candidate-data capture: RAW_CANDIDATE only, holdout protected, no training path.

Owner authorisation LOCAL_CANDIDATE_DATA_COLLECTION_ONLY (2026-09-24). These
tests check the boundaries rather than the convenience:
- the store lives outside the repository;
- corpus cases and their near paraphrases are EVAL_HOLDOUT with training_allowed=false;
- only RAW_CANDIDATE is ever written, and never to the SFT or DPO stores;
- rejected responses are kept as negative evidence;
- deletion leaves a content-free tombstone;
- the tool has no network or training imports.
"""
import importlib.util
import json
from pathlib import Path
import re
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def report(label, projection, text, reply, *, case="P5_casual_sharing", status="completed"):
    return {"label": label, "code_revision": "abc123", "started_at": "2026-09-24T06:17:02-0600",
            "persona_projection": projection,
            "model": {"identity": {"file": {"name": "Qwen_Qwen3.5-4B-Q4_K_M.gguf", "sha256": "13c16f42"},
                                   "matches_manifest": True},
                      "server_sampling": {"settings": {"temperature": 0.8}, "server": {"build": "b11062"}},
                      "sent_sampling": {}},
            "cases": [{"id": case, "turns": [{
                "input": text, "status": status, "raw_generation": reply, "released_text": reply,
                "released_segments": [reply], "request_id": label + "-r1", "condition": "casual_share",
                "read": "responds as herself?", "scope": "private",
                "plan": {"persona_projection": projection, "persona_sha256": projection * 8},
                "sent_messages": [{"role": "system", "content": "…"}, {"role": "user", "content": text}]}]}]}


class CandidateDataTests(unittest.TestCase):
    def setUp(self):
        self.tool = _load("candidate_data", "tools/candidate_data.py")
        self.harness = _load("acceptance_dialogue", "tools/acceptance_dialogue.py")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.store = str(self.base / "store")
        self.tool._open_store(self.store, create=True)

    def package(self, text, replies, case="P5_casual_sharing"):
        paths = []
        for (label, projection), reply in zip((("qwen4b-v4-r1", "v4"), ("qwen4b-v5-r1", "v5")), replies):
            path = self.base / f"{label}-{abs(hash(text))}.json"
            path.write_text(json.dumps(report(label, projection, text, reply, case=case), ensure_ascii=False),
                            encoding="utf-8")
            paths.append(path)
        review, key = self.base / "review.json", self.base / "key.json"
        self.harness.blind(paths, review, key, seed=7)
        mapping = json.loads(key.read_text(encoding="utf-8"))["key"][f"{case}#1"]
        return paths, review, key, mapping

    def judge(self, item_id, preferred, labels=None):
        path = self.base / "judgments.json"
        path.write_text(json.dumps({"judgments": [{"id": item_id, "preferred": preferred, "reason": "更自然",
                                                   "labels": labels}]}, ensure_ascii=False), encoding="utf-8")
        return path

    def read(self, name):
        text = (Path(self.store) / self.tool.FILES[name]).read_text(encoding="utf-8")
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def test_store_must_be_outside_the_repository(self):
        with self.assertRaises(self.tool.CandidateDataError):
            self.tool._open_store(str(ROOT / "candidate-store"), create=True)
        self.assertFalse((ROOT / "candidate-store").exists())
        manifest = json.loads((Path(self.store) / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["authorisation"], "LOCAL_CANDIDATE_DATA_COLLECTION_ONLY")
        self.assertEqual(manifest["writable_states"], ["RAW_CANDIDATE"])
        self.assertFalse(manifest["training_allowed_by_this_tool"])

    def test_corpus_review_goes_to_the_holdout_with_full_provenance(self):
        paths, review, key, mapping = self.package("今天下雨了。", ("下雨了。你那边大吗？", "下雨天适合发呆。"))
        preferred = next(letter for letter, label in mapping.items() if label == "qwen4b-v5-r1")
        counts = self.tool.ingest_review(self.store, review, key, self.judge("P5_casual_sharing#1", preferred,
                                         {preferred: {"label": "pass"}}), paths)
        self.assertEqual((counts["eval_holdout"], counts["raw_preferences"], counts["rejected_failures"]), (1, 0, 1))
        [record] = self.read("eval_holdout")
        self.assertEqual((record["lifecycle_state"], record["source_role"], record["training_allowed"]),
                         ("RAW_CANDIDATE", "eval_holdout", False))
        self.assertEqual(record["preference"]["preferred"], preferred)
        provenance = record["provenance"]["reports"][0]
        for field in ("model_sha256", "model_file", "code_revision", "persona_projection", "server_sampling",
                      "sent_sampling", "started_at"):
            self.assertIn(field, provenance)
        self.assertEqual({r["arm_label"] for r in record["responses"]}, {"qwen4b-v4-r1", "qwen4b-v5-r1"})
        self.assertTrue(all(value is None for value in record["integrity_review"].values()))
        [rejected] = self.read("rejected_failures")
        self.assertEqual(rejected["response"]["arm_label"], "qwen4b-v4-r1")
        self.assertEqual((self.read("sft_candidates"), self.read("dpo_candidates")), ([], []))

    def test_a_near_paraphrase_of_a_corpus_input_is_holdout(self):
        self.assertTrue(self.tool.is_eval_holdout("今天下雨啦"))
        self.assertTrue(self.tool.is_eval_holdout("anything", "P8_correction_and_pressure"))
        self.assertFalse(self.tool.is_eval_holdout("周末要不要一起去看新上映的那部电影"))

    def test_non_corpus_review_is_a_raw_candidate_and_ingest_is_idempotent(self):
        text = "周末要不要一起去看新上映的那部电影"
        paths, review, key, mapping = self.package(text, ("好啊。", "看你安排。"), case="LIVE_session")
        judgments = self.judge("LIVE_session#1", "tie")
        self.tool.ingest_review(self.store, review, key, judgments, paths)
        self.tool.ingest_review(self.store, review, key, judgments, paths)
        [record] = self.read("raw_preferences")
        self.assertEqual((record["source_role"], record["training_allowed"]), ("review", False))
        self.assertEqual(self.read("rejected_failures"), [])  # a tie rejects nothing

    def test_owner_edits_keep_original_edit_and_diff(self):
        edits = self.base / "edits.json"
        edits.write_text(json.dumps({"edits": [
            {"case_id": "P5_casual_sharing", "turn": 1, "input": "今天下雨了。",
             "original": "下雨了。你那边大吗？", "edited": "下雨天适合什么都不干。", "reason": "别反问"},
            {"input": "周末要不要一起去看新上映的那部电影", "original": "好的呀，需要我帮你查场次吗？",
             "edited": "可以，不过我只能听你讲剧情。"}]}, ensure_ascii=False), encoding="utf-8")
        counts = self.tool.ingest_edits(self.store, edits)
        self.assertEqual((counts["eval_holdout"], counts["raw_edits"]), (1, 1))
        [edit] = self.read("raw_edits")
        self.assertIn("+可以，不过我只能听你讲剧情。", edit["diff"])
        self.assertEqual((edit["lifecycle_state"], edit["training_allowed"]), ("RAW_CANDIDATE", False))

    def test_nothing_but_raw_candidates_can_be_written(self):
        root = Path(self.store)
        record = {"id": "x", "lifecycle_state": "RAW_CANDIDATE", "training_allowed": False}
        for store_name in ("sft_candidates", "dpo_candidates"):
            with self.assertRaises(self.tool.CandidateDataError):
                self.tool._append(root, store_name, record)
        with self.assertRaises(self.tool.CandidateDataError):
            self.tool._append(root, "raw_edits", {**record, "lifecycle_state": "TRAINING_CANDIDATE"})
        with self.assertRaises(self.tool.CandidateDataError):
            self.tool._append(root, "raw_edits", {**record, "training_allowed": True})
        public = [name for name in dir(self.tool) if not name.startswith("_")]
        self.assertFalse([name for name in public if re.search(r"promot|train|export|upload", name, re.I)])

    def test_forget_leaves_only_a_tombstone(self):
        paths, review, key, mapping = self.package("今天下雨了。", ("甲", "乙"))
        self.tool.ingest_review(self.store, review, key, self.judge("P5_casual_sharing#1", "A"), paths)
        [record] = self.read("eval_holdout")
        self.assertEqual(self.tool.forget(self.store, record["id"], "owner request"), 2)
        self.assertEqual((self.read("eval_holdout"), self.read("rejected_failures")), ([], []))
        [tombstone] = self.read("deletions")
        self.assertEqual(set(tombstone), {"id", "deleted_at", "reason", "records_removed"})

    def test_no_network_or_training_imports(self):
        source = (ROOT / "tools/candidate_data.py").read_text(encoding="utf-8")
        forbidden = r"^\s*(?:import|from)\s+(?:httpx|requests|urllib|socket|http|ftplib|smtplib|torch|transformers|peft|trl|unsloth|datasets|sqlite3)\b"
        self.assertIsNone(re.search(forbidden, source, re.M))
        self.assertNotIn("ExperienceStore", source)
        training = re.compile(r"^\s*(?:import|from)\s+(?:torch|transformers|peft|trl|unsloth|datasets|accelerate|bitsandbytes|deepspeed)\b", re.M)
        offenders = [str(path.relative_to(ROOT)) for path in ROOT.rglob("*.py")
                     if ".venv" not in path.parts and "venv" not in path.parts
                     and training.search(path.read_text(encoding="utf-8", errors="ignore"))]
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
