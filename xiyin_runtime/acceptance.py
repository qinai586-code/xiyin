"""Native Windows acceptance of the unified runtime without a model or devices."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile

import xiyin_paths
from .authorization import authorize_runtime
from .contracts import InputEvent
from .runtime import XIYINRuntime


async def exercise_runtime(runtime, workspace):
    """Real SQLite, agenda, verified file body, memory, sleep and adopted policy."""
    runtime.register_workspace(workspace)
    original = await runtime.dispatch(InputEvent("remember", {"text": "验收偏好：短篇解谜", "kind": "preference"}))
    corrected = await runtime.dispatch(InputEvent("remember", {"text": "验收偏好：长篇解谜", "kind": "preference",
                                                               "supersedes": original["memory_id"]}))
    if [m["id"] for m in runtime.store.memories()] != [corrected["memory_id"]]:
        raise AssertionError("Memory replacement did not become current")
    goal = await runtime.dispatch(InputEvent("goal", {"title": "验证文件写入和读取", "steps": [
        {"operation": "write_text", "arguments": {"path": "acceptance.txt", "text": "栖音闭环"}},
        {"operation": "read_text", "arguments": {"path": "acceptance.txt"}},
    ]}))
    job = await runtime.dispatch(InputEvent("tick"))
    if job["status"] != "completed" or (Path(workspace) / "acceptance.txt").read_text(encoding="utf-8") != "栖音闭环":
        raise AssertionError("Goal did not complete verified real file actions")
    evidence = job["result"]["receipts"][0]["event_id"]
    active = await runtime.dispatch(InputEvent("learn", {"goal": "缩小已授权文件动作的单次预算",
        "evidence_refs": [evidence], "strategy": {"max_read_bytes": 16, "max_write_bytes": 16,
        "verify_after_write": True, "encoding": "utf-8"}}))
    if active.get("policy", {}).get("max_write_bytes") != 16:
        raise AssertionError("Evaluated policy was not adopted")
    denied = await runtime.dispatch(InputEvent("action", {"operation": "write_text",
        "arguments": {"path": "too-large.txt", "text": "x" * 20}}))
    if denied["status"] != "failure" or (Path(workspace) / "too-large.txt").exists():
        raise AssertionError("Adopted strategy did not govern real execution")
    await runtime.dispatch(InputEvent("rollback_strategy"))
    allowed = await runtime.dispatch(InputEvent("action", {"operation": "write_text",
        "arguments": {"path": "after-rollback.txt", "text": "x" * 20}}))
    if allowed["status"] != "success":
        raise AssertionError("Previous executable strategy was not restored")
    sleep = await runtime.dispatch(InputEvent("sleep"))
    if sleep["interrupted"] or runtime.sleep_controller.state()["phase"] != "sleeping":
        raise AssertionError("Sleep checkpoint was not completed")
    await runtime.dispatch(InputEvent("wake"))
    if runtime.sleep_controller.state()["phase"] != "awake":
        raise AssertionError("Wake failed")
    await runtime.dispatch(InputEvent("stop"))
    try:
        await runtime.dispatch(InputEvent("action", {"operation": "read_text", "arguments": {"path": "acceptance.txt"}}))
    except RuntimeError:
        pass
    else:
        raise AssertionError("Stopped runtime dispatched an action")
    await runtime.dispatch(InputEvent("resume"))
    identity = runtime.self_state.persistent_id
    return {"memory_id": corrected["memory_id"], "character_identity": identity,
            "goal_id": goal["id"], "checks": ["memory_correction", "verified_file_actions", "goal_scheduling",
                "strategy_adoption_affects_execution", "strategy_rollback", "sleep_checkpoint", "wake", "stop_resume"]}


async def verify_native():
    """Uses actual host authorization; no bypass flag or fixture model exists."""
    authorize_runtime()
    previous = os.environ.get(xiyin_paths.DATA_ENV)
    from .cli import initialize_data
    from .supervisor import restore_backup
    try:
        with tempfile.TemporaryDirectory(prefix="xiyin-no-model-") as directory:
            base = Path(directory).resolve()
            data, workspace = base / "data", base / "workspace"
            data.mkdir()
            workspace.mkdir()
            os.environ[xiyin_paths.DATA_ENV] = str(data)
            initialized = initialize_data()
            runtime = XIYINRuntime.open(model_enabled=False)
            try:
                result = await exercise_runtime(runtime, workspace)
                runtime.supervisor.create_backup(base / "backup")
                runtime.remember("备份后临时内容")
            finally:
                await runtime.shutdown()
            restored = restore_backup(base / "backup", data, initialized["data_root_id"])
            reopened = XIYINRuntime.open(model_enabled=False)
            try:
                if reopened.self_state.persistent_id != result["character_identity"]:
                    raise AssertionError("Character identity changed across restore/restart")
                if [m["id"] for m in reopened.store.memories()] != [result["memory_id"]]:
                    raise AssertionError("Backup did not restore the real memory database")
                if reopened.store.read_document("goals", result["goal_id"])["value"]["status"] != "completed":
                    raise AssertionError("Goal history did not survive restart")
            finally:
                await reopened.shutdown()
            return {"status": "passed", "mode": "native_host_no_model", "model_requests": 0,
                    "checks": result["checks"] + ["sqlite_backup_restore", "identity_and_goal_restart"],
                    "real_device_tested": False, "natural_dialogue_tested": False,
                    "production_data_used": False, "temporary_data_removed_on_exit": True}
    finally:
        if previous is None:
            os.environ.pop(xiyin_paths.DATA_ENV, None)
        else:
            os.environ[xiyin_paths.DATA_ENV] = previous
