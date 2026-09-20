# -*- coding: utf-8 -*-
# Archived predecessor: no runtime imports or management operations.
raise RuntimeError("Legacy QINAI code is archived and disabled; use the current xiyin.py entry.")

import argparse
import os
import sys
import unicodedata
from pathlib import Path

import memory_review_tool


def _xiyin_init_root():
    """A4/P2 极薄入口加载接线：一次性显式加载便携根解析器。

    固定布局 <运行根>\\xiyin_paths.py（本文件位于 <运行根>\\L5_SAFE\\ADMIN_TOOLS）；
    无上溯、无旧盘符回退；不为加载路径启动 L2/模型；sys.modules 中已存在
    且 __file__ 不符的同名伪模块（cwd/PYTHONPATH 注入）直接拒绝。
    """
    import importlib.util
    here = os.path.dirname(os.path.abspath(__file__))
    expected = os.path.join(os.path.dirname(os.path.dirname(here)),
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
    return sys.modules["xiyin_paths"].project_root()


_XIYIN_ROOT = _xiyin_init_root()


def _xiyin_identity():
    """A4/P3 共享身份适配器一次性显式加载（固定布局 <运行根>\\xiyin_identity.py；
    同名伪模块拒绝；无环境变量改选配置来源）。"""
    import importlib.util
    expected = os.path.join(str(_XIYIN_ROOT), "xiyin_identity.py")
    preloaded = sys.modules.get("xiyin_identity")
    if preloaded is not None and os.path.abspath(
            getattr(preloaded, "__file__", "")) != os.path.abspath(expected):
        raise RuntimeError("xiyin_identity pseudo-module rejected: "
                           + repr(getattr(preloaded, "__file__", None)))
    if preloaded is None:
        spec = importlib.util.spec_from_file_location("xiyin_identity",
                                                      expected)
        module = importlib.util.module_from_spec(spec)
        sys.modules["xiyin_identity"] = module
        spec.loader.exec_module(module)
    return sys.modules["xiyin_identity"]


# 仅作 operator 参数的显示默认值；授权完全取决于令牌 SID 与部署策略，
# 与该常量无关（P3/A2 解绑；审核+快照恢复共用 reviewer 身份集）。
EXPECTED_OPERATOR = None
SCRIPT_DIR = Path(__file__).resolve().parent


def _validate_import_source():
    tool_path = Path(memory_review_tool.__file__).resolve()
    if tool_path.parent != SCRIPT_DIR:
        raise RuntimeError("memory_review_tool import source mismatch")


def _require_admin_user():
    """Verify the current token; write confirmation belongs to the operation."""
    return memory_review_tool._require_admin_user()


def _has_control_char(value: str) -> bool:
    return any(unicodedata.category(ch).startswith("C") for ch in value)


def _validate_filename_arg(filename: str) -> str:
    if not isinstance(filename, str) or not filename:
        raise ValueError("Filename is required")
    if "\x00" in filename:
        raise ValueError("Invalid filename: NUL byte")
    if unicodedata.normalize("NFKC", filename) != filename:
        raise ValueError(f"Invalid filename: {filename}")
    if filename != filename.strip():
        raise ValueError(f"Invalid filename: {filename}")
    if os.path.isabs(filename) or filename.startswith(("\\\\", "//")):
        raise ValueError(f"Invalid filename: {filename}")
    if filename != os.path.basename(filename):
        raise ValueError(f"Invalid filename: {filename}")
    if any(token in filename for token in ("..", "/", "\\", ":")):
        raise ValueError(f"Invalid filename: {filename}")
    if _has_control_char(filename):
        raise ValueError(f"Invalid filename: {filename}")
    return memory_review_tool._validate_filename(filename)


def _validate_reason_arg(reason: str) -> str:
    return memory_review_tool._validate_reason(reason)


def _build_parser():
    parser = argparse.ArgumentParser(
        prog="review_cli.py",
        description="XIYIN memory review; writes require explicit Windows console confirmation.",
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("self-check", help="validate CLI, import source, and configured governance paths")
    subparsers.add_parser("list", help="list valid pending wait_check files")

    show_parser = subparsers.add_parser("show", help="show a pending file")
    show_parser.add_argument("filename")

    approve_parser = subparsers.add_parser("approve", help="approve a pending file")
    approve_parser.add_argument("filename")

    reject_parser = subparsers.add_parser("reject", help="reject a pending file")
    reject_parser.add_argument("filename")
    reject_parser.add_argument("--reason", required=True)

    return parser


def main(argv=None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2

    try:
        _validate_import_source()
        operator = _require_admin_user()
        memory_review_tool.validate_config_paths()

        if args.command == "self-check":
            print("SELF_CHECK_OK")
            return 0

        if args.command == "list":
            for name in memory_review_tool.list_pending_files():
                print(name)
            return 0

        if args.command == "show":
            filename = _validate_filename_arg(args.filename)
            print(memory_review_tool.read_pending_file(filename))
            return 0

        if args.command == "approve":
            filename = _validate_filename_arg(args.filename)
            dst = memory_review_tool.approve_memory(filename, operator=operator)
            print(f"APPROVED {os.path.basename(dst)}")
            return 0

        if args.command == "reject":
            filename = _validate_filename_arg(args.filename)
            reason = _validate_reason_arg(args.reason)
            dst = memory_review_tool.reject_memory(filename, reason=reason, operator=operator)
            print(f"REJECTED {os.path.basename(dst)}")
            return 0

        parser.print_help()
        return 2

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
