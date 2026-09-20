# C:\L0_RUNTIME\L2_CENTRAL\C6_WRITEBACK\c6_submit.py
import os
import time
import shutil
import tempfile
import uuid


def _xiyin_init_root():
    """A4/P4 (C6_WRITEBACK) 极薄入口加载接线：一次性显式加载便携根解析器。

    固定布局 <运行根>/xiyin_paths.py；无上溯、无旧盘符回退；不为加载路径
    启动 L2/模型；sys.modules 中已存在且 __file__ 不符的同名伪模块
    （cwd/PYTHONPATH 注入）直接拒绝。"""
    import importlib.util
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    expected = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "xiyin_paths.py")
    preloaded = sys.modules.get("xiyin_paths")
    if preloaded is not None and os.path.abspath(
            getattr(preloaded, "__file__", "")) != os.path.abspath(expected):
        raise RuntimeError("xiyin_paths pseudo-module rejected: "
                           + repr(getattr(preloaded, "__file__", None)))
    if preloaded is None:
        spec = importlib.util.spec_from_file_location("xiyin_paths", expected)
        module = importlib.util.module_from_spec(spec)
        sys.modules["xiyin_paths"] = module
        spec.loader.exec_module(module)
    return sys.modules["xiyin_paths"]


_XIYIN_ROOT = _xiyin_init_root().project_root()

# P4: 候选写回目录由同一受信数据根派生（与审核端/C2 同根，读写不分叉）
WAIT_CHECK_DIR = str(_xiyin_init_root().resolve_path("data") / "wait_check")
SAFE_DISK_FREE_MB = 50


def c6_submit_memory(user_input: str, qinai_reply: str) -> tuple:
    """
    Function: C6 写回闸门，将经过 C4 规则引擎校验的对话对提交至 L1 wait_check 待审队列。
    Input:    user_input (str) — 原始用户输入（长度 ≤ 10000 字符）；
              qinai_reply (str) — C4 校验通过的祈奈回复（长度 ≤ 5000 字符）。
    Output:   (True, "MEMORY_OK:<filename>") 写入成功；
              (False, "MEMORY_REJECTED_<reason>") 或 (False, "MEMORY_ERROR:<detail>") 失败。
    Depends:  utils_guard.check_rules_engine / qinai_normalize；os、shutil、tempfile、uuid、time；
              WAIT_CHECK_DIR 常量（C:\L0_RUNTIME\L1_MEMORY\wait_check）。
    Security: 二次规则引擎校验防止 C4 旁路内容污染记忆库；
              输入长度硬上限防止超大内容写入；
              磁盘余量检查（≥50MB）防写入损坏；
              原子写入（tempfile + os.replace）+ fsync + 完整性验证，防止部分写入；
              仅写入 wait_check，绝不直接写 passed，保持记忆审核门禁完整。
    """
    if len(user_input) > 10000 or len(qinai_reply) > 5000:
        return (False, "MEMORY_REJECTED_INPUT_OVERSIZE")

    try:
        import utils_guard
    except ImportError:
        return (False, "MEMORY_REJECTED_GUARD_DOWN")

    if not hasattr(utils_guard, "check_rules_engine"):
        return (False, "MEMORY_REJECTED_GUARD_DOWN")

    is_safe, hit_detail = utils_guard.check_rules_engine(qinai_reply, caller="C6")
    if not is_safe:
        rule_type = hit_detail.get("type", "UNIFIED_RULE").upper()
        return (False, f"MEMORY_REJECTED_{rule_type}")

    try:
        paths = _xiyin_init_root()
        paths._inside(_XIYIN_ROOT, paths.Path(WAIT_CHECK_DIR))
        os.makedirs(WAIT_CHECK_DIR, exist_ok=True)

        _, _, free_bytes = shutil.disk_usage(WAIT_CHECK_DIR)
        free_mb = free_bytes / (1024 * 1024)
        if free_mb < SAFE_DISK_FREE_MB:
            return (False, f"MEMORY_REJECTED_DISK_LOW:{free_mb:.1f}MB")

        safe_user = utils_guard.qinai_normalize(user_input)
        safe_reply = utils_guard.qinai_normalize(qinai_reply)
        content = f"用户：{safe_user}\n祈奈：{safe_reply}"

        fd, temp_path = tempfile.mkstemp(dir=WAIT_CHECK_DIR, prefix="tmp_", text=True)
        fd_owner = "raw"

        try:
            with os.fdopen(fd, "w+", encoding="utf-8", newline="") as f:
                fd_owner = "with"
                f.write(content)
                f.flush()
                os.fsync(f.fileno())

                f.seek(0)
                if f.read() != content:
                    raise ValueError("INTEGRITY_CHECK_FAILED")

            timestamp = int(time.time())
            unique_id = uuid.uuid4().hex
            final_path = os.path.join(WAIT_CHECK_DIR, f"{timestamp}_{unique_id}_chat.txt")

            for _ in range(3):
                try:
                    os.replace(temp_path, final_path)
                    break
                except PermissionError:
                    time.sleep(0.1)
            else:
                raise PermissionError("AV_LOCK_TIMEOUT")

            return (True, f"MEMORY_OK:{os.path.basename(final_path)}")

        except Exception:
            if fd_owner == "raw":
                try:
                    os.close(fd)
                except OSError:
                    pass

            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
            raise

    except Exception as e:
        return (False, f"MEMORY_ERROR:{str(e)[:60]}")
