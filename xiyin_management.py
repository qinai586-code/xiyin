"""Explicit console confirmation for legacy memory management operations.

This is an application confirmation boundary, not Windows account isolation.
Code running as the same user can modify Python, files, or inject GUI input;
neither a console handle nor this in-process lease prevents those attacks.
"""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import secrets
import sys
import threading
import uuid


_ROOT = Path(__file__).resolve().parent
_ACTIONS = {"MEMORY_APPROVE", "MEMORY_REJECT", "SNAPSHOT_CREATE", "SNAPSHOT_RESTORE"}
_LOCK = threading.RLock()
_ACTIVE = {}


class ManagementCancelled(PermissionError):
    """The operator did not confirm this specific action and target scope."""


class ManagementAuditError(RuntimeError):
    """Audit persistence failed; an already attempted operation may have changed data."""


def _root(root):
    candidate = Path(root).resolve(strict=True)
    if candidate != _ROOT:
        raise PermissionError("Management root does not match this installation")
    return candidate


def _identity():
    expected = _ROOT / "xiyin_identity.py"
    module = sys.modules.get("xiyin_identity")
    if module is not None:
        if Path(getattr(module, "__file__", "")).resolve() != expected:
            raise RuntimeError("xiyin_identity import source mismatch")
        return module
    spec = importlib.util.spec_from_file_location("xiyin_identity", expected)
    module = importlib.util.module_from_spec(spec)
    sys.modules["xiyin_identity"] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop("xiyin_identity", None)
        raise
    return module


def verified_operator(root, operator=None):
    """Read the actual process token; display text never supplies authority."""
    root = _root(root)
    identity = _identity()
    policy = identity.load_policy(root)
    role, sid = identity.current_role(policy)
    required = "runtime" if policy.get("mode") == "single_user" else "reviewer"
    if role != required:
        raise PermissionError(f"Management token role {role!r} is not permitted")
    verified = identity.reviewer_display_name(policy, sid)
    if operator is not None and (not isinstance(operator, str) or operator.casefold() != verified.casefold()):
        raise PermissionError("Operator argument does not match the verified Windows token")
    return verified


def _safe_path(root, value):
    candidate = Path(value)
    if not candidate.is_absolute() or not candidate.resolve().is_relative_to(root):
        raise PermissionError("Management target escapes the installation")
    # Refuse links even when they resolve back inside this installation.
    lexical = Path(os.path.abspath(candidate))
    if not lexical.is_relative_to(root):
        raise PermissionError("Management target escapes the installation")
    for item in (lexical, *lexical.parents):
        if item == root:
            break
        if os.path.lexists(item):
            attributes = item.lstat()
            if item.is_symlink() or getattr(attributes, "st_file_attributes", 0) & 0x400:
                raise PermissionError("Management target contains a link or reparse point")
    return str(lexical)


def _targets(root, targets):
    if not isinstance(targets, dict) or not targets:
        raise ValueError("An explicit management target scope is required")
    if any(not isinstance(key, str) or not key.isidentifier() for key in targets):
        raise ValueError("Invalid management target label")
    return {key: _safe_path(root, value) for key, value in sorted(targets.items())}


def _append_audit(root, record):
    path = Path(_safe_path(root, root / "L5_SAFE/review_audit/management_actions.jsonl"))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        with path.open("r", encoding="utf-8") as stream:
            last = None
            for line in stream:
                if line.strip():
                    last = json.loads(line)
        if last != record:
            raise ValueError("Management audit read-back mismatch")
    except (OSError, ValueError) as exc:
        raise ManagementAuditError("Management audit could not be persisted and verified") from exc


def _console_answer(prompt):
    """Use console device handles directly, never inherited stdin/stdout pipes."""
    if os.name != "nt":
        raise PermissionError("Management confirmation requires a Windows console")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetConsoleMode.restype = wintypes.BOOL
    kernel.FlushConsoleInputBuffer.argtypes = [wintypes.HANDLE]
    kernel.FlushConsoleInputBuffer.restype = wintypes.BOOL
    kernel.WriteConsoleW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, wintypes.DWORD,
                                     ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    kernel.WriteConsoleW.restype = wintypes.BOOL
    kernel.ReadConsoleW.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                                    ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    kernel.ReadConsoleW.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handles = []
    try:
        for name in ("CONIN$", "CONOUT$"):
            handle = kernel.CreateFileW(name, 0xC0000000, 3, None, 3, 0, None)
            if handle in (None, ctypes.c_void_p(-1).value):
                raise PermissionError("No interactive Windows console is available")
            handles.append(handle)
            mode = wintypes.DWORD()
            if not kernel.GetConsoleMode(handle, ctypes.byref(mode)):
                raise PermissionError("Management confirmation handle is not a console")
            if name == "CONIN$" and not mode.value & 2:
                raise PermissionError("Console line input is required for confirmation")
        if not kernel.FlushConsoleInputBuffer(handles[0]):
            raise PermissionError("Unable to prepare console confirmation")
        written = wintypes.DWORD()
        if not kernel.WriteConsoleW(handles[1], prompt, len(prompt), ctypes.byref(written), None) or written.value != len(prompt):
            raise PermissionError("Unable to display the complete management request")
        buffer = ctypes.create_unicode_buffer(256)
        count = wintypes.DWORD()
        if not kernel.ReadConsoleW(handles[0], buffer, 255, ctypes.byref(count), None):
            raise PermissionError("Unable to read console confirmation")
        answer = buffer[:count.value]
        if not answer.endswith(("\n", "\r")):
            raise ManagementCancelled("Incomplete console confirmation")
        return answer.strip()
    finally:
        failed = False
        for handle in reversed(handles):
            failed = not kernel.CloseHandle(handle) or failed
        if failed:
            raise PermissionError("Unable to close management console handles")


def require_scope(lease, root, actions, targets):
    """Private-operation guard: only a live confirmed lease covers its targets."""
    root = _root(root)
    with _LOCK:
        try:
            active = _ACTIVE.get(lease)
        except TypeError:
            active = None
        record = active["request"] if active is not None else None
        wanted = _targets(root, targets)
        if (record is None or record["root"] != str(root) or record["action"] not in actions
                or any(record["targets"].get(key) != value for key, value in wanted.items())):
            raise PermissionError("No live confirmation covers this action and target scope")
        claim = tuple(wanted.items())
        if claim in active["claimed"]:
            raise PermissionError("This confirmed operation scope has already been used")
        active["claimed"].add(claim)


@contextmanager
def management_action(root, action, targets, *, operator=None, detail=None):
    """Confirm and audit one operation; never accept a supplied approval flag."""
    root = _root(root)
    if action not in _ACTIONS:
        raise ValueError("Unsupported management action")
    actor = verified_operator(root, operator)
    scope = _targets(root, targets)
    details = json.loads(json.dumps(detail or {}, ensure_ascii=True, allow_nan=False))
    request = {"schema_version": "xiyin.management.v1", "request_id": uuid.uuid4().hex,
               "root": str(root), "action": action, "targets": scope,
               "operator": actor, "detail": details}

    def audit(status, **extra):
        _append_audit(root, {**request, "status": status,
                           "time": datetime.now(timezone.utc).isoformat(), **extra})

    with _LOCK:
        audit("REQUESTED", data_may_have_changed=False)
        challenge = f"CONFIRM {action} {secrets.token_hex(4)}"
        prompt = ("\nXIYIN management request (one operation):\n"
                  + json.dumps({"action": action, "targets": scope, "detail": details},
                               ensure_ascii=True, indent=2)
                  + "\nOnly confirm if you intend these changes. Other input cancels.\n"
                  + challenge + "\n> ")
        try:
            answer = _console_answer(prompt)
            if answer != challenge:
                raise ManagementCancelled("Management operation was not confirmed")
        except BaseException as exc:
            audit("CANCELLED" if isinstance(exc, (ManagementCancelled, KeyboardInterrupt)) else "CONFIRMATION_FAILED",
                  error_type=type(exc).__name__, data_may_have_changed=False)
            raise
        audit("CONFIRMED", data_may_have_changed=False)
        lease = object()
        _ACTIVE[lease] = {"request": request, "claimed": set()}
        try:
            yield lease
        except BaseException as exc:
            audit("CANCELLED" if isinstance(exc, KeyboardInterrupt) else "FAILED",
                  error_type=type(exc).__name__, data_may_have_changed=True)
            raise
        else:
            audit("SUCCEEDED", data_may_have_changed=True)
        finally:
            _ACTIVE.pop(lease, None)
