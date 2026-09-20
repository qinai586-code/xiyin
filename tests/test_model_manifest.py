"""Pinned model and downloader checks; no network or real model is used."""

from contextlib import redirect_stderr, redirect_stdout
import copy
import hashlib
from http.client import IncompleteRead
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import URLError
import venv


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("xiyin_download_model", ROOT / "tools" / "download_model.py")
download = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(download)


class Response(io.BytesIO):
    def __init__(self, content, url="https://cdn.example.test/model.gguf", on_read=None):
        super().__init__(content)
        self.url = url
        self.on_read = on_read

    def geturl(self):
        return self.url

    def read(self, size=-1):
        if self.on_read is not None:
            callback, self.on_read = self.on_read, None
            callback()
        return super().read(size)


class ModelManifestTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="xiyin-model-test-")
        self.addCleanup(folder.cleanup)
        self.tmp = Path(folder.name)
        self.payload = b"GGUF synthetic unit-test data"
        self.manifest = copy.deepcopy(download.load_manifest())
        self.manifest["model"]["size"] = len(self.payload)
        self.manifest["model"]["sha256"] = hashlib.sha256(self.payload).hexdigest()
        self.target = self.tmp / "models" / "fixture.gguf"

    def assert_no_partial_files(self):
        self.assertEqual(list(self.tmp.rglob("*.part")), [])

    def test_manifest_matches_verified_hugging_face_metadata(self):
        manifest = download.load_manifest()
        self.assertEqual(manifest["model"], {
            "repo_id": "bartowski/Qwen_Qwen3.5-4B-GGUF",
            "revision": "4168f45a16a1290d65a4ec0fa312ae917a4c15d6",
            "filename": "Qwen_Qwen3.5-4B-Q4_K_M.gguf",
            "size": 3013027808,
            "sha256": "13c16f426047e2de38cd075bdade4a7bcbc8c774384876f677740cda65f8a983",
        })
        self.assertFalse(manifest["reference"]["windows_binary_verified"])
        self.assertEqual(download.model_destination(manifest), ROOT / "models" / manifest["model"]["filename"])

    def test_manifest_rejects_floating_revision_and_unsafe_settings(self):
        for section, field, value in (
            ("model", "revision", "main"), ("model", "filename", "../escape.gguf"),
            ("model", "repo_id", "owner/repo/other"), ("model", "sha256", "not-a-hash"),
            ("model", "size", True), ("server", "host", "0.0.0.0"),
            ("server", "auto_mmproj", True), ("server", "enable_thinking", True),
        ):
            invalid = copy.deepcopy(self.manifest)
            invalid[section][field] = value
            with self.subTest(field=field), patch.object(download.tomllib, "load", return_value=invalid):
                with self.assertRaises(download.ModelError):
                    download.load_manifest()

    def test_download_streams_one_pinned_file_and_publishes_only_after_verification(self):
        opener = Mock(return_value=Response(self.payload))
        with patch.object(download, "CHUNK_SIZE", 4):
            target, status = download.download_model(self.manifest, self.target, opener=opener)
        self.assertEqual((target, status), (self.target, "downloaded"))
        self.assertEqual(self.target.read_bytes(), self.payload)
        request = opener.call_args.args[0]
        model = self.manifest["model"]
        self.assertEqual(request.full_url,
                         f'https://huggingface.co/{model["repo_id"]}/resolve/{model["revision"]}/{model["filename"]}')
        self.assertEqual(opener.call_count, 1)
        self.assert_no_partial_files()

    def test_correct_existing_model_skips_network(self):
        self.target.parent.mkdir()
        self.target.write_bytes(self.payload)
        opener = Mock(side_effect=AssertionError("network must not run"))
        self.assertEqual(download.download_model(self.manifest, self.target, opener=opener)[1], "already-present")
        opener.assert_not_called()

    def test_unknown_existing_file_is_never_overwritten(self):
        self.target.parent.mkdir()
        self.target.write_bytes(b"another file")
        opener = Mock(side_effect=AssertionError("network must not run"))
        with self.assertRaises(download.ModelError):
            download.download_model(self.manifest, self.target, opener=opener)
        self.assertEqual(self.target.read_bytes(), b"another file")
        opener.assert_not_called()
        self.assert_no_partial_files()

    def test_corrupt_truncated_and_oversized_downloads_leave_no_model(self):
        for content in (b"X" * len(self.payload), self.payload[:-1], self.payload + b"extra"):
            with self.subTest(content=content), self.assertRaises(download.ModelError):
                download.download_model(self.manifest, self.target, opener=Mock(return_value=Response(content)))
            self.assertFalse(self.target.exists())
            self.assert_no_partial_files()

    def test_network_failure_and_insecure_redirect_leave_no_model(self):
        broken = Response(self.payload)
        broken.read = Mock(side_effect=IncompleteRead(b"partial", len(self.payload)))
        for opener in (
            Mock(side_effect=URLError("offline")),
            Mock(return_value=Response(self.payload, url="http://cdn.example.test/model.gguf")),
            Mock(return_value=broken),
        ):
            with self.assertRaises(download.ModelError):
                download.download_model(self.manifest, self.target, opener=opener)
            self.assertFalse(self.target.exists())
            self.assert_no_partial_files()

    def test_file_appearing_during_download_is_not_overwritten(self):
        response = Response(self.payload, on_read=lambda: self.target.write_bytes(b"unrelated concurrent file"))
        with self.assertRaises(download.ModelError):
            download.download_model(self.manifest, self.target, opener=Mock(return_value=response))
        self.assertEqual(self.target.read_bytes(), b"unrelated concurrent file")
        self.assert_no_partial_files()

    def test_simultaneous_correct_download_can_be_reused(self):
        response = Response(self.payload, on_read=lambda: self.target.write_bytes(self.payload))
        result = download.download_model(self.manifest, self.target, opener=Mock(return_value=response))
        self.assertEqual(result[1], "already-present")
        self.assertEqual(self.target.read_bytes(), self.payload)
        self.assert_no_partial_files()

    def test_check_cli_is_read_only_and_reports_the_verified_manifest(self):
        self.target.parent.mkdir()
        self.target.write_bytes(self.payload)
        output = io.StringIO()
        with patch.object(download, "load_manifest", return_value=self.manifest), patch.object(download, "urlopen") as opener:
            with redirect_stdout(output):
                result = download.main(["--check", "--destination", str(self.target)])
        self.assertEqual(result, 0)
        value = json.loads(output.getvalue())
        self.assertEqual(value["status"], "verified")
        self.assertEqual(value["server"]["host"], "127.0.0.1")
        self.assertFalse(value["server"]["enable_thinking"])
        self.assertFalse(value["server"]["auto_mmproj"])
        opener.assert_not_called()

    def test_check_missing_model_does_not_create_directories(self):
        with patch.object(download, "load_manifest", return_value=self.manifest), redirect_stderr(io.StringIO()):
            self.assertEqual(download.main(["--check", "--destination", str(self.target)]), 1)
        self.assertFalse(self.target.parent.exists())

    @unittest.skipUnless(os.name == "nt", "Launcher subprocess behavior requires native Windows")
    def test_windows_launcher_selects_project_python_and_explicit_override(self):
        launcher_root = self.tmp / "launcher project"
        scripts = launcher_root / "tools"
        scripts.mkdir(parents=True)
        launcher = scripts / "start_model.ps1"
        shutil.copyfile(ROOT / "tools" / "start_model.ps1", launcher)
        record = self.tmp / "interpreter.json"
        # Run an actual checker process but deliberately fail model verification
        # before the launcher can start any server or read model weights.
        (scripts / "download_model.py").write_text(
            'import json, os, pathlib, sys\n'
            'pathlib.Path(os.environ["XIYIN_TEST_INTERPRETER"]).write_text('
            'json.dumps({"executable": sys.executable, "argv": sys.argv[1:]}), encoding="utf-8")\n'
            'raise SystemExit(37)\n', encoding="utf-8")
        environment = os.environ.copy()
        environment["XIYIN_TEST_INTERPRETER"] = str(record)
        shells = list(dict.fromkeys(path for name in ("powershell.exe", "pwsh.exe")
                                   if (path := shutil.which(name))))
        self.assertTrue(shells, "Windows CI must provide PowerShell")

        def run(shell, extra=()):
            return subprocess.run(
                [shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-File", str(launcher), "-ServerPath", sys.executable, *extra],
                cwd=self.tmp, env=environment, capture_output=True,
                encoding="utf-8", errors="replace", timeout=30)

        for shell in shells:
            with self.subTest(shell=shell, python="missing default"):
                result = run(shell)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("-Mode setup", result.stdout + result.stderr)
                self.assertFalse(record.exists())
            with self.subTest(shell=shell, python="explicit without project venv"):
                result = run(shell, ("-PythonPath", sys.executable))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Model verification failed", result.stdout + result.stderr)
                used = json.loads(record.read_text(encoding="utf-8"))
                self.assertTrue(Path(used["executable"]).samefile(sys.executable))
                self.assertEqual(used["argv"], ["--check"])
                record.unlink()

        venv.EnvBuilder(with_pip=False).create(launcher_root / ".venv")
        project_python = launcher_root / ".venv" / "Scripts" / "python.exe"
        for shell in shells:
            for extra, expected in (((), project_python), (("-PythonPath", sys.executable), Path(sys.executable))):
                with self.subTest(shell=shell, python=str(expected)):
                    result = run(shell, extra)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("Model verification failed", result.stdout + result.stderr)
                    used = json.loads(record.read_text(encoding="utf-8"))
                    # Windows can expand TEMP's 8.3 alias in sys.executable.
                    # Check file identity, not two spellings of the same path.
                    self.assertTrue(Path(used["executable"]).samefile(expected))
                    self.assertEqual(used["argv"], ["--check"])
                    record.unlink()

    @unittest.skipUnless(os.name == "nt", "PowerShell parser and Windows argv require native Windows")
    def test_windows_launcher_syntax_and_argument_round_trip(self):
        import ctypes
        from ctypes import wintypes

        powershell = shutil.which("powershell.exe") or shutil.which("pwsh.exe")
        self.assertIsNotNone(powershell, "Windows CI must provide PowerShell")
        values = ['--chat-template-kwargs', '{"enable_thinking":false}',
                  'C:\\栖音 models\\voice.gguf', 'path with trailing slash\\', '']
        environment = os.environ.copy()
        environment["XIYIN_TEST_LAUNCHER"] = str(ROOT / "tools" / "start_model.ps1")
        environment["XIYIN_TEST_ARGUMENTS"] = json.dumps(values)
        command = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:XIYIN_TEST_LAUNCHER, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors -join '; ') }
$function = $ast.Find({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'ConvertTo-WindowsArgument' }, $true)
if (-not $function) { throw 'Missing argument encoder' }
Invoke-Expression $function.Extent.Text
$values = ConvertFrom-Json $env:XIYIN_TEST_ARGUMENTS
@($values | ForEach-Object { ConvertTo-WindowsArgument $_ }) | ConvertTo-Json -Compress
'''
        result = subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-Command", command],
                                env=environment, check=True, capture_output=True, encoding="utf-8-sig")
        quoted = json.loads(result.stdout)
        command_line = 'stub.exe ' + ' '.join(quoted)
        split = ctypes.windll.shell32.CommandLineToArgvW
        split.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
        split.restype = ctypes.POINTER(wintypes.LPWSTR)
        argc = ctypes.c_int()
        argv = split(command_line, ctypes.byref(argc))
        self.assertTrue(argv)
        try:
            self.assertEqual([argv[index] for index in range(1, argc.value)], values)
        finally:
            free = ctypes.windll.kernel32.LocalFree
            free.argtypes = [ctypes.c_void_p]
            free.restype = ctypes.c_void_p
            free(argv)


if __name__ == "__main__":
    unittest.main(verbosity=2)
