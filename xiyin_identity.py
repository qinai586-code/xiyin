# -*- coding: utf-8 -*-
"""Windows token identity and explicit local deployment policy.

The default single_user mode has no account-name or machine-SID allowlist.
It reads the real process token for attribution; runtime permission also needs
valid deployment paths and resource checks. Management uses its own explicit
console confirmation, not a second Windows login. This is an application guard,
not isolation from other programs running as the same Windows user.

Existing separate-account deployments remain opt-in compatible: omission of
identity.mode retains the old disjoint SID lists, without a silent fallback.
The policy comes only from <code root>/config/deployment.toml, never environment
variables. Windows token failures are fatal; usernames are never authority.
Thread impersonation is not supported: identity is the process primary token.
"""
from __future__ import annotations

import ctypes
import importlib.util
import os
import re
import sys
import tomllib
from ctypes import wintypes
from pathlib import Path

__all__ = [
    "IdentityConfigError", "TokenReadError",
    "current_token_sid", "load_policy", "role_for_sid", "current_role",
    "reviewer_display_name", "policy_path_for_root", "validate_runtime_cwd",
]

POLICY_RELPATH = os.path.join("config", "deployment.toml")

# 严格 SID 语法：S-1-<revision 已定>-<subauthority(1..15)>，各数字部分
# 1-10 位且无前导零（"0" 本身除外）。ConvertSidToStringSidW 输出满足之。
_SID_PART = r"(?:0|[1-9][0-9]{0,9})"
_SID_RE = re.compile(rf"^S-1-(?:0|[1-9][0-9]{{0,14}})(?:-{_SID_PART}){{1,15}}$")
_SID_MAX_LEN = 184


def _valid_sid(value):
    if not isinstance(value, str) or not _SID_RE.fullmatch(value):
        return False
    parts = [int(part) for part in value.split("-")[2:]]
    return parts[0] <= (1 << 48) - 1 and all(p <= (1 << 32) - 1 for p in parts[1:])


class IdentityConfigError(RuntimeError):
    """机器身份配置缺失/损坏/非法 —— 一律拒绝（fail closed）。"""


class TokenReadError(RuntimeError):
    """进程令牌读取失败（Windows API 层） —— 一律拒绝（fail closed）。"""


# ---------------------------------------------------------------------------
# 进程令牌 SID 读取（纯机制；无回退）
# ---------------------------------------------------------------------------
class _SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


class _TOKEN_USER(ctypes.Structure):
    _fields_ = [("User", _SID_AND_ATTRIBUTES)]


def _load_advapi32():
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD)]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    kernel32.GetCurrentProcess.argtypes = []
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    return advapi32, kernel32


def current_token_sid() -> str:
    """当前进程主令牌的用户 SID（字符串形态）。任何 API 失败即抛
    TokenReadError；绝不回退用户名/环境变量。"""
    if os.name != "nt":
        raise TokenReadError("Windows process tokens are unavailable on this platform")
    advapi32, kernel32 = _load_advapi32()
    TOKEN_QUERY = 0x0008
    TokenUser = 1
    ERROR_INSUFFICIENT_BUFFER = 122

    h_process = kernel32.GetCurrentProcess()  # 伪句柄，无需关闭
    h_token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(h_process, TOKEN_QUERY,
                                     ctypes.byref(h_token)):
        raise TokenReadError(
            f"OpenProcessToken failed: {ctypes.get_last_error()}")
    try:
        needed = wintypes.DWORD(0)
        if advapi32.GetTokenInformation(h_token, TokenUser, None, 0,
                                        ctypes.byref(needed)):
            raise TokenReadError(
                "GetTokenInformation size probe unexpectedly succeeded")
        if ctypes.get_last_error() != ERROR_INSUFFICIENT_BUFFER:
            raise TokenReadError(
                "GetTokenInformation size probe failed: "
                f"{ctypes.get_last_error()}")
        buf = ctypes.create_string_buffer(needed.value)
        if not advapi32.GetTokenInformation(
                h_token, TokenUser, buf, needed.value, ctypes.byref(needed)):
            raise TokenReadError(
                f"GetTokenInformation read failed: {ctypes.get_last_error()}")
        token_user = ctypes.cast(buf, ctypes.POINTER(_TOKEN_USER)).contents
        sid_ptr = token_user.User.Sid
        if not sid_ptr:
            raise TokenReadError("TokenUser.Sid is NULL")
        sid_str = ctypes.c_wchar_p()
        if not advapi32.ConvertSidToStringSidW(
                ctypes.c_void_p(sid_ptr), ctypes.byref(sid_str)):
            raise TokenReadError(
                f"ConvertSidToStringSidW failed: {ctypes.get_last_error()}")
        try:
            value = sid_str.value
        finally:
            # LocalFree returns HLOCAL: NULL == success (nonzero == failure)
            if kernel32.LocalFree(ctypes.cast(sid_str, wintypes.HLOCAL)):
                raise TokenReadError("LocalFree(sid string) failed")
        if not _valid_sid(value) or len(value) > _SID_MAX_LEN:
            raise TokenReadError(f"token SID failed strict grammar: {value!r}")
        return value
    finally:
        if not kernel32.CloseHandle(h_token):
            raise TokenReadError("CloseHandle(token) failed")


# ---------------------------------------------------------------------------
# 严格机器配置读取
# ---------------------------------------------------------------------------
def policy_path_for_root(root: Path | str) -> Path:
    """策略文件路径：仅由运行根派生；不接受环境变量改选。"""
    return Path(root) / POLICY_RELPATH


def _is_reparse(path: Path) -> bool:
    try:
        info = os.lstat(path)
        return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & 0x400)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise IdentityConfigError(f"Cannot inspect policy path {path}: {exc}") from exc


def _require_sid_list(raw, label: str) -> list:
    if not isinstance(raw, list) or not raw:
        raise IdentityConfigError(f"{label} must be a nonempty list")
    out = []
    for item in raw:
        if not isinstance(item, str) or not _valid_sid(item) \
                or len(item) > _SID_MAX_LEN:
            raise IdentityConfigError(f"{label} contains an illegal SID: {item!r}")
        out.append(item)
    return out


def _portable_runtime_path(root: Path, entry: str) -> Path:
    # C1 can be executed by absolute filename without the code root on sys.path.
    # Load the sibling resolver explicitly, rejecting a preloaded namesake.
    expected = Path(__file__).resolve().with_name("xiyin_paths.py")
    paths = sys.modules.get("xiyin_paths")
    if paths is not None and Path(getattr(paths, "__file__", "")).resolve() != expected:
        raise IdentityConfigError("xiyin_paths pseudo-module rejected")
    if paths is None:
        spec = importlib.util.spec_from_file_location("xiyin_paths", expected)
        paths = importlib.util.module_from_spec(spec)
        sys.modules["xiyin_paths"] = paths
        try:
            spec.loader.exec_module(paths)
        except BaseException:
            sys.modules.pop("xiyin_paths", None)
            raise
    try:
        return paths.under(root, entry)
    except paths.XiyinPathError as exc:
        raise IdentityConfigError(f"Invalid runtime relative directory: {exc}") from exc


def load_policy(root: Path | str) -> dict:
    """读取并严格校验 <运行根>\\config\\deployment.toml。

    任何缺失/损坏/链接/非法条目 -> IdentityConfigError（拒绝）。
    返回结构（调用方只读）：mode、角色 SID 列表、显示名及已解析的 cwd。
    single_user 不使用 SID 列表；没有 mode 的旧配置继续严格分离账户。"""
    root = Path(root).resolve(strict=True)
    path = policy_path_for_root(root)
    # A plain leaf is insufficient when its config parent is a junction.
    if _is_reparse(path.parent) or not path.resolve(strict=False).is_relative_to(root):
        raise IdentityConfigError("machine identity config escaped its trusted root")
    if not path.exists():
        raise IdentityConfigError(f"machine identity config missing: {path}")
    if _is_reparse(path):
        raise IdentityConfigError(
            f"machine identity config is a reparse point: {path}")
    if not path.is_file():
        raise IdentityConfigError(
            f"machine identity config is not a regular file: {path}")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise IdentityConfigError(
            f"machine identity config unreadable/invalid: {exc}") from exc

    known_top = {"identity", "runtime"}
    unknown_top = set(data) - known_top
    if unknown_top:
        raise IdentityConfigError(f"unknown config tables: {sorted(unknown_top)}")

    identity = data.get("identity")
    if not isinstance(identity, dict):
        raise IdentityConfigError("[identity] table missing or invalid")
    mode = identity.get("mode", "separate_accounts")
    if mode not in ("single_user", "separate_accounts"):
        raise IdentityConfigError("identity.mode must be single_user or separate_accounts")
    known_identity_keys = {"mode"}
    if mode == "separate_accounts":
        known_identity_keys |= {"runtime_sids", "reviewer_sids", "review_display"}
    unknown_identity = set(identity) - known_identity_keys
    if unknown_identity:
        raise IdentityConfigError(
            f"unknown [identity] keys for {mode}: {sorted(unknown_identity)}")
    runtime_sids, reviewer_sids, review_display = [], [], {}
    if mode == "separate_accounts":
        runtime_sids = _require_sid_list(identity.get("runtime_sids"),
                                         "identity.runtime_sids")
        reviewer_sids = _require_sid_list(identity.get("reviewer_sids"),
                                          "identity.reviewer_sids")
        overlap = sorted(set(runtime_sids) & set(reviewer_sids))
        if overlap:
            raise IdentityConfigError(
                f"runtime_sids and reviewer_sids must not overlap: {overlap}")

        raw_display = identity.get("review_display")
        if not isinstance(raw_display, dict) or not raw_display:
            raise IdentityConfigError(
                "[identity.review_display] table missing or invalid")
        review_display = {}
        for sid, name in raw_display.items():
            if not _valid_sid(sid):
                raise IdentityConfigError(f"review_display key is not a SID: {sid!r}")
            if not isinstance(name, str) or not name.strip() or "\x00" in name \
                    or any(ord(c) < 32 for c in name):
                raise IdentityConfigError(
                    f"review_display name for {sid} is not a clean nonempty string")
            review_display[sid] = name
        unknown_display = sorted(set(review_display) - set(reviewer_sids))
        if unknown_display:
            raise IdentityConfigError(
                f"review_display contains non-reviewer SIDs: {unknown_display}")
        missing_display = sorted(set(reviewer_sids) - set(review_display))
        if missing_display:
            raise IdentityConfigError(
                f"reviewer SIDs without display name: {missing_display}")

    runtime_tbl = data.get("runtime")
    if not isinstance(runtime_tbl, dict):
        raise IdentityConfigError("[runtime] table missing or invalid")
    unknown_runtime = set(runtime_tbl) - {"allowed_cwd_roots"}
    if unknown_runtime:
        raise IdentityConfigError(
            f"unknown [runtime] keys: {sorted(unknown_runtime)}")
    raw_roots = runtime_tbl.get("allowed_cwd_roots")
    if not isinstance(raw_roots, list) or not raw_roots:
        raise IdentityConfigError(
            "runtime.allowed_cwd_roots must be a nonempty list")
    allowed_cwd_roots = []
    seen_normcase = set()
    for entry in raw_roots:
        if not isinstance(entry, str) or not entry.strip():
            raise IdentityConfigError(
                f"allowed_cwd_roots entry is not a nonempty string: {entry!r}")
        if mode == "single_user":
            # Same portable component rules as config/paths.toml; no drive,
            # expansion, traversal, empty components, or Windows device names.
            p = _portable_runtime_path(root, entry)
            raw = root
            for part in entry.split("/"):
                raw /= part
                if _is_reparse(raw):
                    raise IdentityConfigError(f"Runtime directory contains a link: {raw}")
        else:
            p = Path(entry)
            if not p.is_absolute():
                raise IdentityConfigError(
                    f"allowed_cwd_roots entry is not absolute: {entry!r}")
            if _is_reparse(p):
                raise IdentityConfigError(
                    f"allowed_cwd_roots entry is a reparse point: {entry!r}")
        if not p.is_dir():
            raise IdentityConfigError(
                f"allowed_cwd_roots entry does not exist as a directory: {entry!r}")
        p = p.resolve(strict=True)
        nc = os.path.normcase(str(p))
        if nc in seen_normcase:
            raise IdentityConfigError(
                f"allowed_cwd_roots duplicate (normcase): {entry!r}")
        seen_normcase.add(nc)
        allowed_cwd_roots.append(str(p))

    return {
        "mode": mode,
        "runtime_sids": runtime_sids,
        "reviewer_sids": reviewer_sids,
        "review_display": review_display,
        "allowed_cwd_roots": allowed_cwd_roots,
    }


# ---------------------------------------------------------------------------
# 角色判定（纯逻辑；SID 来源必须是令牌读取结果）
# ---------------------------------------------------------------------------
ROLE_RUNTIME = "runtime"
ROLE_REVIEWER = "reviewer"


def role_for_sid(policy: dict, sid: str) -> str | None:
    """Classify an OS-derived SID; this pure helper never reads usernames."""
    if not _valid_sid(sid) or len(sid) > _SID_MAX_LEN:
        raise TokenReadError("Invalid process token SID")
    mode = policy.get("mode", "separate_accounts")
    if mode == "single_user":
        return ROLE_RUNTIME
    if mode != "separate_accounts":
        raise IdentityConfigError("Unknown identity mode")
    if sid in policy["runtime_sids"]:
        return ROLE_RUNTIME
    if sid in policy["reviewer_sids"]:
        return ROLE_REVIEWER
    return None


def current_role(policy: dict) -> tuple:
    """(role, sid)：读取当前进程令牌并按策略判定。读取失败即抛。"""
    sid = current_token_sid()
    return role_for_sid(policy, sid), sid


def reviewer_display_name(policy: dict, sid: str) -> str:
    """审核身份的显示名（仅显示/审计文本；绝不用作授权依据）。"""
    if policy.get("mode") == "single_user":
        if not _valid_sid(sid):
            raise TokenReadError("Invalid process token SID")
        return f"Windows user {sid}"
    name = policy["review_display"].get(sid)
    if name is None:
        raise IdentityConfigError(f"no display name for reviewer SID {sid}")
    return name


def validate_runtime_cwd(policy: dict, cwd: Path | str) -> Path:
    """Validate an existing cwd under a configured root; no empty-list fallback.

    Containment uses resolved paths, so a link into another directory cannot
    escape the allowlist. This is not a filesystem race or OS security boundary.
    """
    try:
        current = Path(cwd).resolve(strict=True)
        if not current.is_dir():
            raise IdentityConfigError("Working directory is not a directory")
        if not any(current.is_relative_to(Path(base).resolve(strict=True))
                   for base in policy["allowed_cwd_roots"]):
            raise IdentityConfigError("Working directory is outside the configured runtime locations")
        return current
    except (OSError, RuntimeError) as exc:
        if isinstance(exc, IdentityConfigError):
            raise
        raise IdentityConfigError(f"Working directory check failed: {exc}") from exc
