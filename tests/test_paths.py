"""Portable Root checks use only fresh temporary trees, never runtime data."""

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import uuid


SOURCE = Path(__file__).resolve().parents[1] / "xiyin_paths.py"


class PortablePathsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="xiyin-path-test-")
        self.addCleanup(temporary.cleanup)
        self.tmp = Path(temporary.name).resolve()
        env = patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("XIYIN_DATA_ROOT", None)
        self.root = self.make_tree(self.tmp / "栖音 code root")
        self.paths = self.load(self.root)

    def make_tree(self, root, with_data=True):
        (root / "config").mkdir(parents=True)
        (root / ".xiyin_root").write_text("xiyin-portable-root-v1.1\n", encoding="utf-8")
        (root / "config" / "paths.toml").write_text(
            '[paths]\ndata = "L1_MEMORY"\nasset = "assets/voice-v1.bin"\n', encoding="utf-8")
        shutil.copyfile(SOURCE, root / "xiyin_paths.py")
        if with_data:
            self.make_data(root / "L1_MEMORY", "original")
        return root

    def make_data(self, root, identity):
        root.mkdir(parents=True)
        (root / ".xiyin_data").write_text(
            f"xiyin-data-root v1\nid={identity}\n", encoding="utf-8")
        return root

    @staticmethod
    def load(root):
        spec = importlib.util.spec_from_file_location(
            f"xiyin_paths_test_{uuid.uuid4().hex}", root / "xiyin_paths.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def link_directory(link, target):
        if os.name == "nt":
            # Junctions do not require symlink privileges; a failure fails the
            # test on Windows CI instead of silently skipping its boundary check.
            subprocess.run(
                ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
                check=True, capture_output=True)
        else:
            link.symlink_to(target, target_is_directory=True)

    def test_existing_apis_and_new_data_apis(self):
        self.assertEqual(self.paths.project_root(), self.root)
        self.assertEqual(self.paths.resolve_path("data"), self.root / "L1_MEMORY")
        self.assertEqual(self.paths.resolve_path("asset"), self.root / "assets" / "voice-v1.bin")
        self.assertEqual(self.paths._inside(self.root, self.root / "new"), self.root / "new")
        self.assertEqual(self.paths.data_root(), self.root / "L1_MEMORY")
        self.assertEqual(self.paths.data_root_id(), "original")
        self.assertFalse((self.root / "assets").exists())

    def test_cwd_independent(self):
        original = Path.cwd()
        self.addCleanup(os.chdir, original)
        for current in (self.tmp, self.root / "config", self.root / "L1_MEMORY"):
            os.chdir(current)
            self.assertEqual(self.paths.project_root(), self.root)
            self.assertEqual(self.paths.data_root(), self.root / "L1_MEMORY")

    def test_portable_relative_allowlist(self):
        for good in ("a", "a.b/c-d_e", "L1_MEMORY/wait_check", "v1.2", "_x", "COM10"):
            with self.subTest(good=good):
                self.assertEqual(self.paths.under(self.root, good), self.root.joinpath(*good.split("/")))
        bad_values = (
            "", ".", "..", "/abs", "C:/x", "C:x", "//server/share", "\\\\server\\share",
            "\\\\?\\C:\\x", "\\\\.\\C:\\x", "a\\b", "../up", "a/../b", "a/./b", "a//b",
            "a/", "~/x", "$HOME/x", "%APPDATA%/x", "a:stream", "trail.", "trail ",
            "CON", "con.txt", "COM1", "LPT9.log", "COM¹", "CONIN$", "nul\x00",
            "a\nb", "日本", "a b", "a?b", "a*b", ".hidden", 7, None,
        )
        for bad in bad_values:
            with self.subTest(bad=bad), self.assertRaises(self.paths.XiyinPathError):
                self.paths.under(self.root, bad)

    def test_relative_config_uses_the_same_validation(self):
        config = self.root / "config" / "paths.toml"
        for value in ("../outside", "a//b", "a/./b", "CON.txt", "trailing.", "中文"):
            config.write_text(f"[paths]\ndata = '{value}'\n", encoding="utf-8")
            with self.subTest(value=value), self.assertRaises(self.paths.XiyinPathError):
                self.paths.resolve_path("data")

    def test_under_requires_an_existing_directory(self):
        for base in (self.tmp / "missing", self.root / ".xiyin_root"):
            with self.subTest(base=base), self.assertRaises(self.paths.XiyinPathError):
                self.paths.under(base, "child")
        self.assertFalse((self.tmp / "missing").exists())

    def test_link_or_windows_junction_containment(self):
        outside = self.tmp / "outside"
        outside.mkdir()
        inside = self.root / "actual"
        inside.mkdir()
        self.link_directory(self.root / "escape", outside)
        self.link_directory(self.root / "alias", inside)
        with self.assertRaises(self.paths.XiyinPathError):
            self.paths.under(self.root, "escape/new/file")
        with self.assertRaises(ValueError):
            self.paths._inside(self.root, self.root / "escape" / "new")
        self.assertEqual(self.paths.under(self.root, "alias/new"), inside / "new")

    def test_config_directory_link_escape_is_rejected(self):
        outside = self.tmp / "external_config"
        shutil.move(self.root / "config", outside)
        self.link_directory(self.root / "config", outside)
        with self.assertRaises(self.paths.XiyinPathError):
            self.paths.project_root()

    def test_root_and_data_marker_directory_link_escape_is_rejected(self):
        outside = self.tmp / "outside_marker"
        outside.mkdir()
        for marker, check in (
            (self.root / "L1_MEMORY" / ".xiyin_data", self.paths.data_root),
            (self.root / ".xiyin_root", self.paths.project_root),
        ):
            marker.unlink()
            self.link_directory(marker, outside)
            with self.subTest(marker=marker), self.assertRaises(self.paths.XiyinPathError):
                check()

    @unittest.skipIf(os.name == "nt", "File symlink privileges vary; Windows junctions are tested separately")
    def test_marker_file_symlink_escape_is_rejected_and_internal_link_is_allowed(self):
        marker = self.root / "L1_MEMORY" / ".xiyin_data"
        external = self.tmp / "external_marker"
        external.write_text("xiyin-data-root v1\nid=external\n", encoding="utf-8")
        marker.unlink()
        marker.symlink_to(external)
        with self.assertRaises(self.paths.XiyinPathError):
            self.paths.data_root()
        with self.assertRaises(self.paths.XiyinPathError):
            self.paths.data_root_id()
        marker.unlink()
        internal = marker.parent / "marker_source"
        internal.write_text("xiyin-data-root v1\nid=internal\n", encoding="utf-8")
        marker.symlink_to(internal)
        self.assertEqual(self.paths.data_root_id(), "internal")

    def test_missing_data_or_marker_never_creates_replacement(self):
        data = self.root / "L1_MEMORY"
        shutil.rmtree(data)
        for getter in (self.paths.data_root, self.paths.data_root_id):
            with self.assertRaises(self.paths.XiyinPathError):
                getter()
            self.assertFalse(data.exists())
        data.mkdir()
        for getter in (self.paths.data_root, self.paths.data_root_id):
            with self.assertRaises(self.paths.XiyinPathError):
                getter()
        self.assertEqual(list(data.iterdir()), [])

    def test_marker_format_and_identity_required_by_both_apis(self):
        marker = self.root / "L1_MEMORY" / ".xiyin_data"
        invalid = (
            b"", b"id=x\n", b"wrong\nid=x\n", b"xiyin-data-root v2\nid=x\n",
            b"xiyin-data-root v1\n", b"xiyin-data-root v1\nid=\n",
            b"xiyin-data-root v1\nid=   \n", b"xiyin-data-root v1\nid=x\nid=y\n",
            b"xiyin-data-root v1\nid=x\nunknown=yes\n", b"xiyin-data-root v1\nid=x\x00y\n",
            b"xiyin-data-root v1\nid=x\ty\n", b"xiyin-data-root v1\nid=\xff\n",
        )
        for content in invalid:
            marker.write_bytes(content)
            for getter in (self.paths.data_root, self.paths.data_root_id):
                with self.subTest(content=content, getter=getter.__name__), self.assertRaises(self.paths.XiyinPathError):
                    getter()
        marker.write_bytes(b"xiyin-data-root v1\r\nid=valid-id\r\n")
        self.assertEqual(self.paths.data_root_id(), "valid-id")

    def test_explicit_override_wins_without_a_default_data_entry(self):
        external = self.make_data(self.tmp / "独立 data root", "external")
        os.environ["XIYIN_DATA_ROOT"] = str(external)
        (self.root / "config" / "paths.toml").write_text('[paths]\n', encoding="utf-8")
        self.assertEqual(self.paths.data_root(), external)
        self.assertEqual(self.paths.data_root_id(), "external")

    def test_valid_override_does_not_bypass_code_root_validation(self):
        external = self.make_data(self.tmp / "external_data", "external")
        os.environ["XIYIN_DATA_ROOT"] = str(external)
        for relative in (".xiyin_root", "config/paths.toml"):
            path = self.root / relative
            content = path.read_bytes()
            path.unlink()
            with self.subTest(relative=relative), self.assertRaises(self.paths.XiyinPathError):
                self.paths.data_root()
            path.write_bytes(content)

    def test_invalid_override_never_falls_back_to_valid_default(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        for raw in (
            "", " ", "relative", "C:relative", "\\rooted", "//server/share", "\\\\server\\share",
            "\\\\?\\C:\\data", "\\\\.\\C:\\data", str(self.tmp / "missing"), str(empty),
            str(self.root / ".xiyin_root"), str(self.tmp / "trailing."), str(self.tmp / "trailing "),
            str(self.tmp / "CON.txt"), str(self.tmp / "a:stream"),
        ):
            os.environ["XIYIN_DATA_ROOT"] = raw
            for getter in (self.paths.data_root, self.paths.data_root_id):
                with self.subTest(raw=raw, getter=getter.__name__), self.assertRaises(self.paths.XiyinPathError):
                    getter()
        self.assertFalse((self.tmp / "missing").exists())

    def test_bad_config_and_missing_keys_fail_explicitly(self):
        config = self.root / "config" / "paths.toml"
        for content in ("not valid toml", "[other]\nx=1", "paths = 'not a table'", "[paths]\ndata=7"):
            config.write_text(content, encoding="utf-8")
            with self.subTest(content=content), self.assertRaises(self.paths.XiyinPathError):
                self.paths.resolve_path("data")
        config.write_text('[paths]\ndata="L1_MEMORY"', encoding="utf-8")
        for name in ("missing", None, []):
            with self.subTest(name=name), self.assertRaises(self.paths.XiyinPathError):
                self.paths.resolve_path(name)

    def test_missing_code_markers_and_config_are_explicit_failures(self):
        for relative in ("config/paths.toml", ".xiyin_root"):
            path = self.root / relative
            content = path.read_bytes()
            path.unlink()
            with self.subTest(relative=relative), self.assertRaises(self.paths.XiyinPathError):
                self.paths.project_root()
            path.write_bytes(content)

    def test_moved_tree_reads_new_identity_after_old_tree_is_offline(self):
        relocated = self.tmp / "搬迁 target" / "runtime"
        shutil.copytree(self.root, relocated)
        (relocated / "L1_MEMORY" / ".xiyin_data").write_text(
            "xiyin-data-root v1\nid=relocated\n", encoding="utf-8")
        self.assertEqual((self.root / "config" / "paths.toml").read_bytes(),
                         (relocated / "config" / "paths.toml").read_bytes())
        self.root.rename(self.root.with_name("old_OFFLINE"))
        moved = self.load(relocated)
        self.assertEqual(moved.project_root(), relocated)
        self.assertEqual(moved.data_root(), relocated / "L1_MEMORY")
        self.assertEqual(moved.data_root_id(), "relocated")

    def test_code_move_without_data_fails_closed(self):
        relocated = self.tmp / "code_only"
        shutil.copytree(self.root, relocated, ignore=shutil.ignore_patterns("L1_MEMORY"))
        moved = self.load(relocated)
        with self.assertRaises(moved.XiyinPathError):
            moved.data_root()
        self.assertFalse((relocated / "L1_MEMORY").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
