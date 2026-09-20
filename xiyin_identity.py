# -*- coding: utf-8 -*-
"""XIYIN 薄共享身份适配器 + 严格机器配置读取（P3，A2/A3）。

一个共享实现，供 C1 与全部审核/管理入口复用；不在各模块复制 ctypes
或账户解析逻辑。定位与加载：各消费方以自身 __file__ 锚定运行根后，
按固定布局 <运行根>\\xiyin_identity.py 一次性显式加载本模块（与
xiyin_paths.py 相同的加载协议；同名伪模块拒绝）。

适用假设（明确写出，未验证的场景不得宣称覆盖）：
  - 本模块读取的是当前【进程主令牌】（GetCurrentProcess ->
    OpenProcessToken(TOKEN_QUERY)）。
  - 不跟随、不假设线程模拟令牌（ThreadImpersonation）。若部署形态
    使用模拟，必须先另行验证再扩展本模块。
  - 任何 Windows API 失败（打开令牌、尺寸探测、缓冲读取、SID 转换、
    句柄/内存释放）一律抛 TokenReadError 拒绝，绝不回退 getpass、
    环境变量或用户名比较。

机器配置（deployment contract，候选形态）：
  - 位置：<运行根>\\config\\deployment.toml —— 由运行根派生，不接受
    任何环境变量改选/重定向（A3：生产授权入口不得凭调用方可改的
    环境变量选择 SID 白名单）。最终生产受信位置由部署契约裁决。
  - 结构（tomllib，严格）：
      [identity]
      runtime_sids  = ["S-1-..."]   # 运行身份（原 SJ_Run 职责）
      reviewer_sids = ["S-1-..."]   # 审核+快照恢复身份（原 SJ_Admin
                                    # 合并职责，A2：不擅自拆分）
      [identity.review_display]
      "S-1-..." = "显示名"           # 仅显示/审计文本，绝不参与授权
      [runtime]
      allowed_cwd_roots = ["C:\\..."]  # 运行 cwd 受信位置（原 C1
                                       # ALLOWED_EXEC_PATH 语义）
  - 校验（全部失败即拒绝，缺/坏/链/非法条目不放过）：
      配置缺失 / 非常规文件 / 本身是重解析点 / 解析错误 / 未知键或表 /
      runtime_sids 与 reviewer_sids 交集非空 / SID 不符合严格语法 /
      reviewer 无显示名 / 显示名映射含未知 SID / allowed_cwd_roots
      非绝对、不存在、本身是重解析点、normcase 重复。
  - 测试注入方式：仅通过构造合成运行树（本模块没有任何测试后门；
    真实入口不继承任何默认开启的测试绕过）。
"""
from __future__ import annotations

import ctypes
import os
import re
import tomllib
from ctypes import wintypes
from pathlib import Path

__all__ = [
    "IdentityConfigError", "TokenReadError",
    "current_token_sid", "load_policy", "role_for_sid", "current_role",
    "reviewer_display_name", "policy_path_for_root",
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
        return bool(os.lstat(str(path)).st_file_attributes & 0x400)
    except OSError:
        return False


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


def load_policy(root: Path | str) -> dict:
    """读取并严格校验 <运行根>\\config\\deployment.toml。

    任何缺失/损坏/链接/非法条目 -> IdentityConfigError（拒绝）。
    返回结构（调用方只读）：
      {"runtime_sids": [...], "reviewer_sids": [...],
       "review_display": {sid: name}, "allowed_cwd_roots": [str, ...]}"""
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
    known_identity_keys = {"runtime_sids", "reviewer_sids", "review_display"}
    unknown_identity = set(identity) - known_identity_keys
    if unknown_identity:
        raise IdentityConfigError(
            f"unknown [identity] keys: {sorted(unknown_identity)}")

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
    """SID -> "runtime" | "reviewer" | None。策略加载时已保证两集不相交。"""
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
    name = policy["review_display"].get(sid)
    if name is None:
        raise IdentityConfigError(f"no display name for reviewer SID {sid}")
    return name
