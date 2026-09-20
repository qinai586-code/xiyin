# -*- coding: utf-8 -*-
"""Side-effect-free L2 helper functions for the QINAI G2 eval runner."""
from __future__ import annotations

import base64
import json
import os
import time
from multiprocessing.connection import Client
from typing import Any

# A5: 心跳机器状态位置单一来源（config/runtime.toml [machine].heartbeat_dir）。
# 默认值=历史字面量（行为保持）；生产者链本轮 NOT VERIFIED -> 本项 PARTIAL；
# 不扫描其他项目、不启动服务找生产者。
def _heartbeat_dir() -> str:
    import importlib.util
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    expected = os.path.join(os.path.dirname(os.path.dirname(here)), "xiyin_paths.py")
    pre = sys.modules.get("xiyin_paths")
    if pre is not None and os.path.abspath(getattr(pre, "__file__", "")) != os.path.abspath(expected):
        raise RuntimeError("xiyin_paths pseudo-module rejected")
    if pre is None:
        spec = importlib.util.spec_from_file_location("xiyin_paths", expected)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["xiyin_paths"] = mod
        spec.loader.exec_module(mod)
    else:
        mod = pre
    import tomllib
    root = mod.project_root()
    config = mod._inside(root, root / "config" / "runtime.toml")
    with open(config, "rb") as fh:
        cfg = tomllib.load(fh)
    d = cfg["machine"]["heartbeat_dir"]
    if not isinstance(d, str) or not d.strip():
        raise ValueError("runtime.toml [machine].heartbeat_dir must be nonempty")
    return d

STATE_DIR = _heartbeat_dir()
HEARTBEAT_PATH = os.path.join(STATE_DIR, "l2_worker_heartbeat.json")
L2_HEARTBEAT_MAX_AGE_SECONDS = 6.0

__all__ = (
    "read_fresh_l2_heartbeat",
    "get_l2_chat_channel_arg",
    "decode_loopback_channel_arg",
    "send_l2_chat_request",
)


def _is_path_under(path: str, parent: str) -> bool:
    try:
        path_real = os.path.realpath(path)
        parent_real = os.path.realpath(parent)
        return os.path.commonpath([path_real, parent_real]) == parent_real
    except Exception:
        return False


def _read_json_file(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def read_fresh_l2_heartbeat(max_age_seconds: float = L2_HEARTBEAT_MAX_AGE_SECONDS) -> tuple[dict | None, str | None]:
    if not _is_path_under(HEARTBEAT_PATH, STATE_DIR):
        return None, "heartbeat path is outside launcher runtime state"
    if not os.path.exists(HEARTBEAT_PATH):
        return None, "missing"
    try:
        heartbeat = _read_json_file(HEARTBEAT_PATH)
    except Exception as exc:
        return None, f"malformed heartbeat: {type(exc).__name__}"
    if not isinstance(heartbeat, dict):
        return None, "malformed heartbeat"
    try:
        age = time.time() - float(heartbeat.get("timestamp", 0))
    except Exception:
        return heartbeat, "heartbeat timestamp is invalid"
    if age > max_age_seconds:
        return heartbeat, f"stale heartbeat age={age:.1f}s"
    return heartbeat, None


def get_l2_chat_channel_arg(heartbeat: dict | None) -> str | None:
    if not isinstance(heartbeat, dict):
        return None
    if not heartbeat.get("ready") or not heartbeat.get("chat_ready"):
        return None
    channel = str(heartbeat.get("chat_channel") or "").strip()
    return channel or None


def decode_loopback_channel_arg(channel_arg: str) -> tuple[str, int, bytes]:
    try:
        payload = json.loads(base64.urlsafe_b64decode(channel_arg.encode("ascii")).decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Invalid loopback channel payload: {exc}") from exc
    host = str(payload.get("host") or "").strip()
    port = int(payload.get("port") or 0)
    authkey_b64 = str(payload.get("authkey_b64") or "").strip()
    if not host or port <= 0 or not authkey_b64:
        raise RuntimeError("Loopback channel payload is incomplete.")
    try:
        authkey = base64.urlsafe_b64decode(authkey_b64.encode("ascii"))
    except Exception as exc:
        raise RuntimeError(f"Invalid loopback channel authkey: {exc}") from exc
    return host, port, authkey


def send_l2_chat_request(channel_arg: str, text: str, *, source: str = "interactive") -> dict:
    host, port, authkey = decode_loopback_channel_arg(channel_arg)
    connection = Client((host, port), family="AF_INET", authkey=authkey)
    try:
        connection.send({"op": "submit", "text": text, "source": source})
        response = connection.recv()
    finally:
        connection.close()
    if not isinstance(response, dict):
        raise RuntimeError("L2 chat channel returned an invalid response.")
    return response
