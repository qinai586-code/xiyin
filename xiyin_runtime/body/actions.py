"""Scoped file and injected desktop adapters; no implicit machine-control grant."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import time
from uuid import uuid4

from .models import AdapterOutcome, Capability, InputRejected, Observation


def _linked(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)


class WorkspaceFileAdapter:
    """A real file read/write test body rooted in an explicitly supplied directory.

    Only direct regular files are supported. This is an application scope guard,
    not an OS sandbox against another process running as the same account.
    """
    def __init__(self, sandbox_root: Path | str, *, adapter_id="workspace", max_bytes=1024 * 1024):
        supplied = Path(sandbox_root).absolute()
        if not supplied.is_dir() or _linked(supplied):
            raise ValueError("An existing, non-linked, explicitly authorized sandbox directory is required")
        self.root = supplied.resolve(strict=True)
        self._identity = (self.root.stat().st_dev, self.root.stat().st_ino)
        self.max_bytes = max_bytes
        self.capability = Capability(adapter_id, "1", ("read_text", "write_text"), True, str(self.root),
                                     "Direct sandbox files only; write success requires readback verification")

    def _check_root(self):
        if not self.root.is_dir() or _linked(self.root) or (self.root.stat().st_dev, self.root.stat().st_ino) != self._identity:
            raise PermissionError("Authorized sandbox directory was replaced or linked")

    def _target(self, name: str) -> Path:
        self._check_root()
        if (not isinstance(name, str) or not name or name in {".", ".."} or
                "/" in name or "\\" in name or ":" in name or "\x00" in name or
                any(character in name for character in '<>"|?*') or name.endswith((" ", ".")) or
                Path(name).is_absolute() or PureWindowsPath(name).drive or PureWindowsPath(name).is_reserved()):
            raise ValueError("Use a single relative filename inside the authorized sandbox")
        target = self.root / name
        if target.exists() or target.is_symlink():
            if _linked(target) or not target.is_file():
                raise PermissionError("Target must be a regular, non-linked file")
            if target.stat().st_nlink > 1:
                raise PermissionError("Hard-linked sandbox files are not supported")
        return target

    async def health(self) -> dict:
        try:
            self._check_root()
            return {"available": True, "version": self.capability.version, "write_access": "verified_per_action"}
        except Exception as exc:
            return {"available": False, "detail": str(exc)}

    async def observe(self) -> Observation:
        self._check_root()
        entries = []
        for path in sorted(self.root.iterdir()):
            stat = path.lstat()
            entries.append((path.name, stat.st_size, stat.st_mtime_ns, stat.st_ino, _linked(path)))
        revision = hashlib.sha256(json.dumps(entries).encode()).hexdigest()
        return Observation(self.capability.adapter_id, self.capability.version, "workspace:" + str(self.root),
                           0, 0, (1.0, 1.0), revision, {"files": [entry[0] for entry in entries]})

    async def execute(self, request, cancel: asyncio.Event) -> AdapterOutcome:
        temporary = None
        committed = False
        try:
            policy = request.policy
            if set(policy) - {"max_read_bytes", "max_write_bytes", "verify_after_write", "encoding"}:
                raise ValueError("Unknown workspace policy fields")
            read_limit = policy.get("max_read_bytes", self.max_bytes)
            write_limit = policy.get("max_write_bytes", self.max_bytes)
            if any(type(value) is not int or not 1 <= value <= min(self.max_bytes, 1024 * 1024)
                   for value in (read_limit, write_limit)):
                raise ValueError("Workspace read/write limits must be integers from 1 to 1 MiB")
            if policy.get("verify_after_write", True) is not True or policy.get("encoding", "utf-8") != "utf-8":
                raise ValueError("Workspace policy requires UTF-8 and verified write readback")
            target = self._target(request.arguments.get("path"))
            if request.scope != str(self.root):
                raise PermissionError("Sandbox scope mismatch")
            if cancel.is_set():
                return AdapterOutcome("cancelled", detail="Cancelled before filesystem action",
                                      evidence={"dispatched": False})
            if request.operation == "read_text":
                with target.open("rb") as stream:
                    content = stream.read(read_limit + 1)
                if len(content) > read_limit:
                    raise ValueError("File exceeds the adapter byte limit")
                text = content.decode("utf-8")
                return AdapterOutcome("success", True, "Read the requested sandbox file",
                                      {"text": text, "dispatched": True, "path": target.name})
            if request.operation != "write_text":
                raise ValueError("Unsupported filesystem operation")
            text = request.arguments.get("text")
            if not isinstance(text, str) or len(text.encode("utf-8")) > min(write_limit, read_limit):
                raise ValueError("Text must fit the adapter byte limit")
            expected = text.encode("utf-8")
            temporary = self.root / (".xiyin-write-" + uuid4().hex)
            with temporary.open("xb") as stream:
                stream.write(expected)
                stream.flush()
                os.fsync(stream.fileno())
            await asyncio.sleep(0)
            if cancel.is_set() or time.monotonic() >= request.deadline:
                return AdapterOutcome("cancelled", detail="Cancelled before atomic replacement; target unchanged",
                                      evidence={"dispatched": False, "write_occurred": False})
            self._target(request.arguments["path"])
            temporary.replace(target)
            temporary = None
            committed = True
            self._target(request.arguments["path"])
            with target.open("rb") as stream:
                actual = stream.read(read_limit + 1)
            if actual != expected:
                return AdapterOutcome("failure", False, "Write readback did not match",
                                      {"write_occurred": True, "dispatched": True, "path": target.name})
            return AdapterOutcome("success", True, "Sandbox write verified by readback",
                                  {"bytes": len(actual), "sha256": hashlib.sha256(actual).hexdigest(),
                                   "path": target.name, "write_occurred": True, "dispatched": True})
        except Exception as exc:
            return AdapterOutcome("unknown" if committed else "failure", detail=f"{type(exc).__name__}: {exc}",
                                  evidence={"write_occurred": committed, "dispatched": committed})
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    async def stop(self) -> dict:
        return {"held_keys": 0, "detail": "Filesystem actions use cooperative cancellation before replacement"}


class DesktopAdapter:
    """Optional UIA/screenshot/input transport supplied by the host.

    Driver contract: async observe()->dict(window_id,width,height,dpi,revision,
    payload), current_window(), send(operation,arguments), verify(request)->bool
    or None, release_key(key). No driver is imported/installed automatically.
    """
    def __init__(self, *, driver=None, allowed_window: str, adapter_id="desktop", version="1"):
        if not allowed_window:
            raise ValueError("A specific authorized window is required")
        self.driver = driver
        self.window = allowed_window
        self._leases = {}
        self._held_keys = set()
        self._release_errors = {}
        self._release_lock = asyncio.Lock()
        self.capability = Capability(adapter_id, version, ("click", "key_down", "key_up"), driver is not None and getattr(driver, "available", True),
                                     allowed_window, "Injected transport only; sending input is not completion",
                                     ("Windows UIA transport", "screenshot backend", "input and focus observer"))

    async def health(self) -> dict:
        if self.driver is not None and hasattr(self.driver, "health"):
            status = await self.driver.health()
            if not status.get("available"):
                return status
        return {"available": self.driver is not None and not self._release_errors, "version": self.capability.version,
                "detail": "Key release was not acknowledged; call stop again before more input" if self._release_errors else
                "Injected driver configured" if self.driver is not None else "UIA/screenshot/input driver not connected"}

    async def observe(self) -> Observation:
        if self.driver is None:
            raise RuntimeError("Desktop driver unavailable")
        data = await self.driver.observe()
        if data["window_id"] != self.window:
            await self.stop()
        return Observation(self.capability.adapter_id, self.capability.version, data["window_id"],
                           data["width"], data["height"], tuple(data["dpi"]), str(data["revision"]),
                           data.get("payload", {}))

    async def _release(self, key: str):
        async with self._release_lock:
            task = self._leases.pop(key, None)
            if task is not None and task is not asyncio.current_task():
                task.cancel()
            try:
                await self.driver.release_key(key)
            except Exception as exc:
                self._release_errors[key] = str(exc)
                raise
            else:
                self._held_keys.discard(key)
                self._release_errors.pop(key, None)

    async def _lease(self, key: str, duration: float):
        deadline = time.monotonic() + duration
        try:
            while time.monotonic() < deadline:
                await asyncio.sleep(min(0.05, max(0, deadline - time.monotonic())))
                if await self.driver.current_window() != self.window:
                    break
            await self._release(key)
        except asyncio.CancelledError:
            # stop()/key_up owns release after cancelling this timer.
            pass
        except Exception as exc:
            # A failed focus read must still attempt release. Retain the lease
            # evidence when release fails, so a later stop can retry it.
            try:
                await self._release(key)
            except Exception:
                self._release_errors[key] = str(exc)

    async def execute(self, request, cancel: asyncio.Event) -> AdapterOutcome:
        if self.driver is None:
            return AdapterOutcome("failure", detail="Desktop driver unavailable",
                                  evidence={"dispatched": False})
        if request.scope != self.window or await self.driver.current_window() != self.window:
            await self.stop()
            # Refused before dispatch. No key, click or focus change was sent.
            return AdapterOutcome("failure", detail="Authorized window is not focused; nothing was dispatched",
                                  evidence={"dispatched": False, "rejected_before_dispatch": True,
                                            "reason": "window_not_focused"})
        if cancel.is_set():
            return AdapterOutcome("cancelled", detail="Cancelled before input dispatch",
                                  evidence={"dispatched": False})
        arguments = request.arguments
        if request.operation == "key_down":
            duration = arguments.get("lease_seconds", 0.25)
            key = arguments.get("key")
            if not isinstance(key, str) or not key or not isinstance(duration, (int, float)) or not 0 < duration <= 1:
                return AdapterOutcome("failure", detail="Key input requires a named key and lease of at most one second",
                                      evidence={"dispatched": False, "rejected_before_dispatch": True,
                                                "reason": "invalid_key_request"})
            if key in self._held_keys:
                return AdapterOutcome("failure", detail="Key already held by an active lease",
                                      evidence={"dispatched": False, "rejected_before_dispatch": True,
                                                "reason": "key_already_held"})
            # Install the release timer before send: a partial send may still press it.
            self._held_keys.add(key)
            self._leases[key] = asyncio.create_task(self._lease(key, duration))
        try:
            if request.operation == "key_up":
                await self._release(arguments["key"])
            else:
                await self.driver.send(request.operation, arguments)
            if cancel.is_set() or await self.driver.current_window() != self.window:
                await self.stop()
                return AdapterOutcome("unknown", detail="Input dispatched, then cancelled or focus changed; keys released",
                                      evidence={"dispatched": True})
            verified = await self.driver.verify(request)
            if verified is True:
                return AdapterOutcome("success", True, "Observed postcondition", {"dispatched": True})
            if verified is False:
                return AdapterOutcome("failure", False, "Input was dispatched and the postcondition was not observed",
                                      {"dispatched": True, "postcondition_observed": False})
            return AdapterOutcome("unknown", False, "Input dispatch is not proof of completion",
                                  {"dispatched": True, "postcondition_observed": None})
        except asyncio.CancelledError:
            await self.stop()
            raise
        except InputRejected as exc:
            # The driver declined before touching the desktop, so this is a
            # refusal to report, not an ambiguous outcome to hedge about.
            await self.stop()
            return AdapterOutcome("failure", detail=f"Refused before dispatch: {exc}",
                                  evidence={"dispatched": False, "rejected_before_dispatch": True,
                                            "reason": "driver_refused"})
        except Exception as exc:
            await self.stop()
            return AdapterOutcome("unknown", detail=f"Input result unverified: {type(exc).__name__}: {exc}",
                                  evidence={"dispatched": True})

    async def stop(self) -> dict:
        keys = list(self._held_keys)
        results = await asyncio.gather(*(self._release(key) for key in keys), return_exceptions=True)
        errors = [str(result) for result in results if isinstance(result, BaseException)]
        return {"released_keys": keys, "release_errors": errors,
                "status": "unknown" if errors else "released"}
