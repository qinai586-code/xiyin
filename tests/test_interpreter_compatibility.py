"""Guards for the two defects a Windows acceptance run surfaced on 3.11/3.13.

A reported run built its virtual environment with whatever `python` happened to
be on PATH, got 3.11, and lost the whole pass to one failure several hundred
cases in. Investigating it found two separate problems, both pinned here:

- `PurePath.is_reserved()` is deprecated in 3.13 and removed in 3.15. Under
  `-W error` it raises instead of answering, which broke every goal and file
  action on 3.13.
- Shutdown recorded a body action's receipt only if the event loop happened to
  schedule the dispatch task enough times before the store closed. 3.12 won
  that race and 3.11 lost it, so the invariant held by luck rather than by
  construction.
"""

import asyncio
from pathlib import Path, PureWindowsPath
import sys
import tempfile
import unittest
import warnings

import xiyin_paths
from xiyin_runtime.cli import SUPPORTED_PYTHON, check_interpreter
from xiyin_runtime.director import _filename


class ReservedWindowsNameTests(unittest.TestCase):
    RESERVED = ("CON", "con.txt", "nul", "COM1", "aux", "LPT9.log", "PRN")
    ORDINARY = ("hello.txt", "note.txt", "normal", "acceptance_note.txt", "console.txt")

    def test_reserved_device_names_are_still_detected(self):
        for name in self.RESERVED:
            with self.subTest(name=name):
                self.assertTrue(xiyin_paths.is_reserved_windows_name(name))

    def test_ordinary_filenames_are_not_treated_as_reserved(self):
        for name in self.ORDINARY:
            with self.subTest(name=name):
                self.assertFalse(xiyin_paths.is_reserved_windows_name(name))

    def test_it_answers_rather_than_raising_under_error_warnings(self):
        # This is the exact shape of the 3.13 failure: the deprecation warning
        # became an exception and every file-skill plan died on it.
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            self.assertTrue(xiyin_paths.is_reserved_windows_name("CON"))
            self.assertFalse(xiyin_paths.is_reserved_windows_name("hello.txt"))
            self.assertEqual(_filename("hello.txt"), "hello.txt")
            with self.assertRaises(ValueError):
                _filename("CON")

    @unittest.skipIf(sys.version_info >= (3, 15),
                     "PurePath.is_reserved() is removed in 3.15; the replacement is already in use")
    def test_the_replacement_agrees_with_the_api_it_replaces(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            for name in self.RESERVED + self.ORDINARY:
                with self.subTest(name=name):
                    self.assertEqual(xiyin_paths.is_reserved_windows_name(name),
                                     PureWindowsPath(name).is_reserved())


class InterpreterReportTests(unittest.TestCase):
    def test_the_tested_range_is_reported_as_supported(self):
        for version in SUPPORTED_PYTHON:
            with self.subTest(version=version):
                self.assertEqual(check_interpreter(version)["state"], "supported")

    def test_an_older_interpreter_is_named_unsupported_not_merely_odd(self):
        report = check_interpreter((3, 11))
        self.assertEqual(report["state"], "unsupported_too_old")
        self.assertIn("rebuild", report["detail"])

    def test_a_newer_interpreter_is_untested_rather_than_claimed_broken(self):
        report = check_interpreter((3, 99))
        self.assertEqual(report["state"], "untested_newer")
        self.assertIn("not evidence", report["detail"])

    def test_the_running_interpreter_is_one_this_repository_tests(self):
        report = check_interpreter()
        # Deliberately a hard failure rather than a skip. An acceptance run on
        # an untested interpreter is what produced a confusing single failure
        # hundreds of cases later; saying so in the first second is the point.
        self.assertEqual(
            report["state"], "supported",
            f"Running Python {report['running']}, outside the tested range "
            f"{report['supported_range']}. Rebuild the virtual environment with "
            f"tools/windows.ps1 -Mode setup before reading any other result.")


class ShutdownDrainTests(unittest.IsolatedAsyncioTestCase):
    """The receipt must be recorded because shutdown waits, not because it raced."""

    async def asyncSetUp(self):
        from xiyin_runtime.config import Settings
        from xiyin_runtime.experience import ExperienceStore
        from xiyin_runtime.provider import ProviderConfig
        from xiyin_runtime.runtime import XIYINRuntime

        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        workspace = Path(self.temp.name) / "workspace"
        workspace.mkdir()
        self.workspace = workspace
        store = ExperienceStore(Path(self.temp.name) / "experience.sqlite3")
        self.store = store
        self.runtime = XIYINRuntime(
            Settings(ProviderConfig("http://localhost:8080/v1", "unused"),
                     Path(__file__).resolve().parents[1] / "config/persona/character.seed.json"),
            store, authorize=lambda: None)
        self.runtime.register_workspace(workspace)

    async def test_an_in_flight_action_is_drained_before_the_store_closes(self):
        from xiyin_runtime.contracts import InputEvent

        task = asyncio.create_task(self.runtime.dispatch(InputEvent("action", {
            "operation": "write_text", "arguments": {"path": "drain.txt", "text": "栖音"}})))
        await asyncio.sleep(0)
        await self.runtime.shutdown()
        result = (await asyncio.gather(task, return_exceptions=True))[0]
        # Shutdown cancels the action, so the file is correctly absent. What
        # must survive is the receipt: the dispatch returns an outcome that
        # reached the ledger, rather than "experience store is closed".
        self.assertNotIsInstance(result, Exception,
                                 "The action receipt must be written before the ledger closes")
        self.assertIn(result["status"], {"cancelled", "success", "unknown", "failure"})
        self.assertTrue(result["event_id"])
        self.assertTrue(self.store._closed)
        self.assertFalse((self.workspace / "drain.txt").exists(),
                         "A cancelled write must leave the target untouched")

    async def test_the_runtime_stops_tracking_a_finished_action(self):
        from xiyin_runtime.contracts import InputEvent

        await self.runtime.dispatch(InputEvent("action", {
            "operation": "write_text", "arguments": {"path": "done.txt", "text": "x"}}))
        self.assertEqual(self.runtime._action_tasks, set())
        await self.runtime.shutdown()


if __name__ == "__main__":
    unittest.main()
