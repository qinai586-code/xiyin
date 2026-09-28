"""The temporary cloud comparison sends only test contexts, never stores the key, and leaves the runtime local."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

import httpx

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("cloud_probe", ROOT / "tools/cloud_probe.py")
tool = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(tool)
KEY = "sk-test-DO-NOT-STORE-0123456789"


class CloudProbeTests(unittest.TestCase):
    def test_contexts_are_replayed_and_the_key_is_never_written(self):
        requests, busy = [], iter([True])

        def server(request):
            if next(busy, False):
                return httpx.Response(429)
            requests.append((str(request.url), request.headers.get("authorization"), json.loads(request.content)))
            return httpx.Response(200, json={"choices": [{"message": {"content": "嗯，挺好。"}, "finish_reason": "stop"}],
                                             "usage": {"completion_tokens": 4}})
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(tool.time, "sleep"):
            out = Path(directory) / "cloud-01"
            result = tool.run("https://api.example.com/v1", "big-model", out, key=KEY,
                              transport=httpx.MockTransport(server), progress=False)
            written = [path.read_bytes() for path in out.iterdir() if path.is_file()]
            with zipfile.ZipFile(out.with_suffix(".zip")) as archive:
                written += [archive.read(name) for name in archive.namelist()]
            report = (out / "REPORT-DRAFT.md").read_text(encoding="utf-8")
        self.assertEqual(len(requests), 52 * tool.SAMPLES)
        url, auth, payload = requests[0]
        self.assertEqual((url, auth), ("https://api.example.com/v1/chat/completions", f"Bearer {KEY}"))
        # Plain OpenAI-compatible fields only: hosted APIs reject llama.cpp extensions.
        self.assertEqual(set(payload), {"model", "messages", "max_tokens", "stream"})
        self.assertEqual(payload["messages"][0]["role"], "system")
        self.assertTrue(all(KEY.encode() not in blob for blob in written))
        self.assertEqual(result["transport_errors"], 0)
        self.assertEqual(result["arm"], {"host": "api.example.com", "model": "big-model", "samples": 2,
                                         "measurement_only": True})
        self.assertIn("CLOUD_VERDICT: LARGE_MODEL_HELPS", report)
        self.assertIn("RUNTIME_CHANGE: NONE", report)

    def test_only_plain_https_is_accepted_and_the_runtime_stays_local(self):
        for bad in ("http://api.example.com/v1", "https://user:pw@api.example.com/v1", "https://api.example.com/v1?key=x"):
            with self.subTest(url=bad), self.assertRaises(SystemExit):
                tool.chat_url(bad)
        self.assertEqual(tool.chat_url("https://api.example.com/v1/chat/completions"),
                         "https://api.example.com/v1/chat/completions")
        from xiyin_runtime.provider import ProviderError, _urls
        with self.assertRaises(ProviderError):
            _urls("https://api.example.com/v1")

    def test_the_key_comes_only_from_the_environment(self):
        with mock.patch.dict(tool.os.environ, {tool.KEY_ENV: ""}), self.assertRaisesRegex(SystemExit, tool.KEY_ENV):
            tool.main(["--base-url", "https://api.example.com/v1", "--model", "m", "--out", "x"])


if __name__ == "__main__":
    unittest.main()
