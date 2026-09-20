# =============================================================================
# 祈奈 AI | P1 人设签名生成工具
# Archived predecessor: no runtime imports or management operations.
raise RuntimeError("Legacy QINAI code is archived and disabled; use the current xiyin.py entry.")
# 存放路径: C:\L0_RUNTIME\L2_CENTRAL\C5_LLM_CALL\script\p1_hash_generator.py
# 运行权限: 必须以 SJ_Admin 身份执行，执行一次后即可锁死
# 用途: 对 D:\L0_RUNTIME\P1_persona_constitution.txt 生成 SHA-256 签名文件
#       解决 P0-5：签名文件不存在导致 P1 人设永远加载失败的问题
# =============================================================================

import os
import hashlib


def _xiyin_init_root():
    """A4/P4 极薄入口加载接线（本文件位于 <运行根>\L2_CENTRAL\C5_LLM_CALL\script）。

    固定布局 <运行根>/xiyin_paths.py；无上溯、无旧盘符回退；不为加载路径
    启动 L2/模型；sys.modules 中已存在且 __file__ 不符的同名伪模块直接拒绝。"""
    import importlib.util
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    expected = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(here))),
                            "xiyin_paths.py")
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

def _xiyin_identity():
# F5: 授权改用共享身份适配器 reviewer 角色，不再比较用户名。
    import importlib.util
    import sys
    expected = os.path.join(str(_XIYIN_ROOT), "xiyin_identity.py")
    preloaded = sys.modules.get("xiyin_identity")
    if preloaded is not None and os.path.abspath(getattr(preloaded, "__file__", "")) != os.path.abspath(expected):
        raise RuntimeError("xiyin_identity pseudo-module rejected")
    if preloaded is None:
        spec = importlib.util.spec_from_file_location("xiyin_identity", expected)
        module = importlib.util.module_from_spec(spec)
        sys.modules["xiyin_identity"] = module
        spec.loader.exec_module(module)
    return sys.modules["xiyin_identity"]

import time

# A7: 人设与哈希成对同源（paths.toml persona_rule/persona_hash）
_P1_PAIR = (_xiyin_init_root().resolve_path("persona_rule"),
            _xiyin_init_root().resolve_path("persona_hash"))
P1_RULE_PATH = _P1_PAIR[0]
P1_HASH_PATH = _P1_PAIR[1]

def generate_p1_hash():
    print("=" * 60)
    print("祈奈AI | P1 人设签名生成工具")
    print("=" * 60)

# F5: 授权改用共享身份适配器 reviewer 角色，不再比较用户名。
    _identity = _xiyin_identity()
    _display = _identity.reviewer_display_name()
    if _display is None:
        print("[F5] no reviewer role")
        return
    print(f"[F5] reviewer: {_display}")

    # 确认 P1 文件存在
    if not os.path.exists(P1_RULE_PATH):
        print(f"错误：P1 人设文件不存在：{P1_RULE_PATH}")
        print("请确认文件已放置到正确路径后重新运行。")
        input("\n按回车退出...")
        return

    # 如果签名文件已存在，警告并询问是否覆盖
    if os.path.exists(P1_HASH_PATH):
        print(f"警告：签名文件已存在：{P1_HASH_PATH}")
        confirm = input("是否重新生成？这将覆盖现有签名（y/n）: ").strip().lower()
        if confirm != "y":
            print("操作已取消。")
            input("\n按回车退出...")
            return

    print(f"\n正在读取 P1 文件：{P1_RULE_PATH}")

    # 计算 SHA-256
    sha256 = hashlib.sha256()
    file_size = 0
    try:
        with open(P1_RULE_PATH, "rb") as f:
            for block in iter(lambda: f.read(4096), b""):
                sha256.update(block)
                file_size += len(block)
    except Exception as e:
        print(f"错误：读取 P1 文件失败：{e}")
        input("\n按回车退出...")
        return

    actual_hash = sha256.hexdigest()
    print(f"文件大小：{file_size} 字节")
    print(f"SHA-256  ：{actual_hash}")

    # 写入签名文件
    try:
        with open(P1_HASH_PATH, "w", encoding="utf-8") as f:
            f.write(actual_hash)
        print(f"\n签名文件已写入：{P1_HASH_PATH}")
    except Exception as e:
        print(f"错误：写入签名文件失败：{e}")
        input("\n按回车退出...")
        return

    # 验证：重新读取签名文件并比对
    try:
        with open(P1_HASH_PATH, "r", encoding="utf-8") as f:
            saved_hash = f.read().strip()
        if saved_hash == actual_hash:
            print("验证通过：签名文件写入正确。")
        else:
            print("错误：签名文件写入后比对失败，请重新运行。")
            input("\n按回车退出...")
            return
    except Exception as e:
        print(f"错误：验证读取失败：{e}")
        input("\n按回车退出...")
        return

    # 写入审计日志
    log_path = os.path.join(str(_XIYIN_ROOT), "L5_SAFE", "G3_AUDIT", "l2_central_audit.log")
    try:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        entry = (
            f"[{ts}] | P1_HASH_GEN    | {_display} | "
            f"P1签名生成完成 hash={actual_hash[:16]}... size={file_size}B\n"
        )
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(entry)
        print(f"审计日志已记录：{log_path}")
    except Exception:
        print("警告：审计日志写入失败（不影响签名结果）。")

    print("\n完成。现在可以启动 l2_central.py，P1 人设将正常加载。")
    input("\n按回车退出...")


if __name__ == "__main__":
    generate_p1_hash()
