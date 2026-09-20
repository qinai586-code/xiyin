"""Small Windows entry: explicit setup, diagnostic, chat, and evidence-backed memory."""

import argparse
import asyncio
from contextlib import aclosing
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import signal
import sys
import uuid

import xiyin_paths
from .authorization import authorize_runtime
from .config import load_settings
from .persona import load_persona
from .provider import LocalModelClient
from .runtime import FoundationRuntime


def initialize_data(*, adopt_existing=False) -> dict:
    """Explicit operator action. Routine startup never creates an empty identity."""
    authorize_runtime()
    xiyin_paths.project_root()
    if xiyin_paths.DATA_ENV in os.environ:
        # An external root must already exist; no recursive creation by override.
        root = xiyin_paths._absolute_data_path(os.environ[xiyin_paths.DATA_ENV])
    else:
        root = xiyin_paths.resolve_path("data")
    marker = root / xiyin_paths.DATA_MARKER
    if marker.exists() or marker.is_symlink():
        return {"data_root": str(xiyin_paths.data_root()), "data_root_id": xiyin_paths.data_root_id(), "created": False}
    if root.exists() and (not root.is_dir() or (any(root.iterdir()) and not adopt_existing)):
        raise ValueError("Existing nonempty data needs an explicit --adopt-existing after backup; no legacy records are imported")
    root.mkdir(parents=True, exist_ok=True)
    identity = uuid.uuid4().hex
    # Exclusive create preserves a concurrently initialized identity.
    with marker.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(f"{xiyin_paths.DATA_MARKER_HEADER}\nid={identity}\n")
        stream.flush()
        os.fsync(stream.fileno())
    return {"data_root": str(xiyin_paths.data_root()), "data_root_id": xiyin_paths.data_root_id(), "created": True}


def doctor(*, probe_model=False) -> tuple[dict, bool]:
    report = {"platform": platform.platform(), "python": platform.python_version(),
              "windows_native": os.name == "nt", "checks": {},
              "audio_and_gpu_performance": "not_measured",
              "runtime_session": "not_started",
              "filesystem_write_access": "not_tested_read_only"}
    checks = report["checks"]
    settings = None
    try:
        settings = load_settings()
        persona = load_persona(settings.persona_path)
        checks["configuration"] = {"ok": True, "code_root": str(xiyin_paths.project_root()), "character": persona.name}
    except Exception as exc:
        checks["configuration"] = {"ok": False, "detail": str(exc)}
    try:
        checks["data"] = {"ok": True, "root": str(xiyin_paths.data_root()), "id": xiyin_paths.data_root_id()}
    except Exception as exc:
        checks["data"] = {"ok": False, "detail": str(exc), "next": "Run init-data explicitly, or select the existing marked data root"}
    identity = {"ok": False}
    try:
        # Read the mode for explanation only. Authorization still validates the
        # real process token and cwd; this diagnostic never substitutes a role.
        import xiyin_identity
        policy = xiyin_identity.load_policy(xiyin_paths.project_root())
        identity["mode"] = policy["mode"]
        identity["account_boundary"] = (
            "current Windows account; management confirmation is application-level, not OS isolation"
            if policy["mode"] == "single_user" else
            "separate runtime/reviewer SID policy; existing account restrictions remain in force"
        )
        authorize_runtime()
        identity["ok"] = True
    except Exception as exc:
        identity["detail"] = str(exc)
    checks["windows_identity"] = identity
    report["dependencies"] = {name: importlib.metadata.version(name) for name in ("httpx", "requests")}
    if probe_model and settings and checks["windows_identity"]["ok"]:
        async def probe():
            provider = LocalModelClient(settings.provider)
            health = await provider.health()
            chunks = []
            async for text in provider.stream([{"role": "user", "content": "请用一句中文问候。"}], asyncio.Event()):
                chunks.append(text)
            reply = "".join(chunks)
            return {"ok": bool(reply.strip()), "health": health, "generated_characters": len(reply), "gpu_offload": "not_verified"}
        try:
            checks["model"] = asyncio.run(probe())
        except Exception as exc:
            checks["model"] = {"ok": False, "detail": str(exc)}
    else:
        checks["model"] = {"ok": None, "detail": "not_probed"}
    ready = all(checks[name].get("ok") is True for name in ("configuration", "data", "windows_identity", "model"))
    report["ready_for_text_runtime"] = ready
    return report, ready


async def _display_turn(runtime, text, args):
    cancel = asyncio.Event()
    loop = asyncio.get_running_loop()
    previous = signal.getsignal(signal.SIGINT)

    def interrupt(signum, frame):
        if cancel.is_set():
            raise KeyboardInterrupt
        loop.call_soon_threadsafe(cancel.set)

    signal.signal(signal.SIGINT, interrupt)
    result = 1
    try:
        async with aclosing(runtime.stream_turn(text, session_id=args.session, scope=args.scope, cancel=cancel)) as events:
            async for event in events:
                if event.type == "text_delta":
                    print(event.text, end="", flush=True)
                elif event.type == "complete":
                    result = 0
                elif event.type == "cancelled":
                    print("\n系统：本轮已取消。", file=sys.stderr)
                    result = 2
                elif event.type == "error":
                    print(f"\n系统：{event.detail}", file=sys.stderr)
    finally:
        signal.signal(signal.SIGINT, previous)
    print()
    return result


async def _run_owned(runtime, operation):
    try:
        return await operation
    finally:
        if hasattr(runtime, "shutdown"):
            await runtime.shutdown()
        else:
            runtime.close()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="xiyin", description="XIYIN: runtime, body, memory, sleep, learning and maintenance")
    commands = parser.add_subparsers(dest="command", required=True)
    diag = commands.add_parser("doctor", help="Read-only diagnostics; model generation only with --probe-model")
    diag.add_argument("--probe-model", action="store_true")
    init = commands.add_parser("init-data", help="Explicitly initialize the selected data root, never import legacy memories")
    init.add_argument("--adopt-existing", action="store_true")
    for name in ("ask", "chat", "remember"):
        sub = commands.add_parser(name)
        sub.add_argument("--session", default="owner")
        sub.add_argument("--scope", choices=("private", "public"), default="private")
        if name in {"ask", "remember"}:
            sub.add_argument("text")
        if name == "remember":
            sub.add_argument("--kind", choices=("fact", "preference", "opinion", "relationship", "goal", "persona"), default="fact")
            sub.add_argument("--subject", default="owner")
            sub.add_argument("--supersedes")
    service = commands.add_parser("serve", help="Authorized local JSON-lines service; one persistent event loop")
    service.add_argument("--workspace", type=Path, help="Explicit existing directory granted to the file body")
    service.add_argument("--window", type=int, help="Explicit native HWND granted to the desktop body")
    service.add_argument("--capture", action="store_true", help="Enable optional Pillow screenshots for that window")
    service.add_argument("--no-model", action="store_true", help="Disable inference, preserve all domain operations")
    commands.add_parser("verify", help="Temporary native-host acceptance without any model or live device calls")
    for name in ("status", "stop", "resume", "sleep", "wake", "tick"):
        commands.add_parser(name)
    operation = commands.add_parser("dispatch", help="Owner console operation as one JSON object")
    operation.add_argument("event", help="JSON InputEvent")
    operation.add_argument("--workspace", type=Path)
    backup = commands.add_parser("backup", help="Consistent backup of the actual experience database")
    backup.add_argument("directory", type=Path)
    restore = commands.add_parser("restore", help="Restore a validated backup with an exclusive stopped-runtime lease")
    restore.add_argument("directory", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            report, ready = doctor(probe_model=args.probe_model)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if ready else 2
        if args.command == "init-data":
            print(json.dumps(initialize_data(adopt_existing=args.adopt_existing), ensure_ascii=False))
            return 0
        if args.command == "verify":
            from .acceptance import verify_native
            print(json.dumps(asyncio.run(verify_native()), ensure_ascii=False, indent=2))
            return 0
        if args.command == "restore":
            from .supervisor import restore_backup
            from xiyin_management import runtime_restore_action
            root = xiyin_paths.data_root()
            with runtime_restore_action(xiyin_paths.project_root(), root, xiyin_paths.data_root_id(), args.directory) as confirmed:
                result = restore_backup(confirmed["backup_dir"], confirmed["data_root"], confirmed["data_root_id"])
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.command in {"stop", "resume"}:
            # A separate owner console can set/clear the stop marker even while
            # the main service owns the database lease. No SQLite is opened here.
            from .supervisor import set_stop_marker
            authorize_runtime()
            result = set_stop_marker(xiyin_paths.data_root(), xiyin_paths.data_root_id(),
                                     stopped=args.command == "stop")
            print(json.dumps(result, ensure_ascii=False))
            return 0
        model_enabled = args.command in {"ask", "chat"} or (args.command == "serve" and not args.no_model)
        runtime = FoundationRuntime.open() if model_enabled else FoundationRuntime.open(model_enabled=False)
        try:
            from .contracts import InputEvent
            if args.command == "serve":
                from .service import serve
                if args.workspace:
                    runtime.register_workspace(args.workspace)
                if args.capture and not args.window:
                    raise ValueError("--capture requires an explicit --window HWND")
                if args.window:
                    from .body.windows import win32_desktop_adapter
                    runtime.body.register(win32_desktop_adapter(args.window, capture=args.capture))
                return asyncio.run(_run_owned(runtime, serve(runtime)))
            if args.command in {"status", "sleep", "wake", "tick", "backup", "dispatch"}:
                if args.command == "dispatch":
                    if args.workspace:
                        runtime.register_workspace(args.workspace)
                    event = InputEvent.from_local_console(json.loads(args.event))
                else:
                    event = InputEvent(args.command, {"directory": str(args.directory)} if args.command == "backup" else {})
                result = asyncio.run(_run_owned(runtime, runtime.dispatch(event)))
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0
            if args.command == "remember":
                print(runtime.remember(args.text, kind=args.kind, subject=args.subject,
                                       session_id=args.session, scope=args.scope, supersedes=args.supersedes))
                return 0
            if args.command == "ask":
                return asyncio.run(_run_owned(runtime, _display_turn(runtime, args.text, args)))
            async def chat_loop():
                print("栖音文字会话。/quit 退出；/remember 内容 保存；/sleep 休息；/wake 唤醒；Ctrl+C 取消回复。")
                while True:
                    text = (await asyncio.to_thread(input, "主理人：")).strip()
                    if text == "/quit":
                        return 0
                    if text.startswith("/remember "):
                        print("系统：", runtime.remember(text[len("/remember "):], session_id=args.session, scope=args.scope))
                    elif text in {"/sleep", "/wake", "/status"}:
                        result = await runtime.dispatch(InputEvent(text[1:], session_id=args.session, scope=args.scope))
                        print("系统：", json.dumps(result, ensure_ascii=False))
                    elif text:
                        print("栖音：", end="", flush=True)
                        await _display_turn(runtime, text, args)
            return asyncio.run(_run_owned(runtime, chat_loop()))
        finally:
            runtime.close()
    except (KeyboardInterrupt, EOFError):
        return 130
    except Exception as exc:
        print(f"系统：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
