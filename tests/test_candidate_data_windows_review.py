"""Independent regressions; synthetic data only, never production stores."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import candidate_data as tool


class CandidateBoundaryReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def test_invalid_explicit_data_root_refuses_before_creation(self):
        dest = self.base / "candidate"
        with patch.dict(os.environ, {tool.xiyin_paths.DATA_ENV: ""}):
            with self.assertRaises(tool.CandidateDataError):
                tool._open_store(str(dest), create=True)
        self.assertFalse(dest.exists())

    def test_valid_explicit_data_root_allows_separate_store(self):
        data = self.base / "data"
        data.mkdir()
        (data / ".xiyin_data").write_text("xiyin-data-root v1\nid=fixture\n", encoding="utf-8")
        with patch.dict(os.environ, {tool.xiyin_paths.DATA_ENV: str(data)}):
            root = tool._open_store(str(self.base / "candidate"), create=True)
            self.assertEqual(tool.status(str(root))["eval_holdout"]["records"], 0)
            with self.assertRaises(tool.CandidateDataError):
                tool._open_store(str(data / "candidate"), create=True)

    def test_hardlinked_store_file_refuses_without_changing_target(self):
        root = tool._open_store(str(self.base / "candidate"), create=True)
        target = self.base / "external-evidence.jsonl"
        target.write_text("SYNTHETIC SENTINEL\n", encoding="utf-8")
        store_file = root / tool.FILES["eval_holdout"]
        store_file.unlink()
        os.link(target, store_file)
        before = target.read_bytes()
        with self.assertRaises(tool.CandidateDataError):
            tool._open_store(str(root))
        self.assertEqual(target.read_bytes(), before)

    def test_ordinary_utf8_store_remains_writable(self):
        root = tool._open_store(str(self.base / "中文 candidate"), create=True)
        record = {"id": "synthetic", "lifecycle_state": "RAW_CANDIDATE",
                  "training_allowed": False, "text": "仅作夹具"}
        self.assertTrue(tool._append(root, "raw_edits", record))
        self.assertEqual(tool._read(root, "raw_edits"), [record])


if __name__ == "__main__":
    unittest.main()
