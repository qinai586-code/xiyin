"""Opt-in, local-only tracing for the isolated synthetic acceptance harness.

Never install this on a production runtime: it deliberately captures prompts
and raw generations. No trace is written to the experience ledger or uploaded.
"""
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from dataclasses import asdict
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import subprocess
from unittest.mock import patch


def fingerprint(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"filename": Path(path).name, "bytes": Path(path).stat().st_size,
            "sha256": digest.hexdigest()}


def provenance(runtime, *, model_file=None, server_binary=None):
    root = Path(__file__).resolve().parents[1]
    def git(*args):
        try:
            return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.DEVNULL,
                                           timeout=5).decode().strip()
        except (OSError, subprocess.SubprocessError):
            return None
    files = [*root.glob("*.py"), *root.glob("xiyin_runtime/**/*.py"), *root.glob("config/**/*.toml"),
             *root.glob("config/persona/*.json"), *root.glob("tools/acceptance*.py")]
    files = sorted(p for p in files if not p.name.startswith("._"))
    dependencies = {}
    for line in (root / "requirements.lock.txt").read_text().splitlines():
        if "==" in line:
            name, expected = line.split("==", 1)
            try:
                actual = version(name)
            except PackageNotFoundError:
                actual = None
            dependencies[name] = {"expected": expected, "actual": actual, "matches": actual == expected}
    return {"git_head": git("rev-parse", "HEAD"), "git_status": git("status", "--short"),
            "source_sha256": {str(p.relative_to(root)): fingerprint(p)["sha256"] for p in files},
            "settings": asdict(runtime.settings),
            "provider_class": type(runtime.provider).__name__,
            "dependencies": dependencies,
            "model_file": fingerprint(model_file) if model_file else None,
            "server_binary": fingerprint(server_binary) if server_binary else None,
            "loaded_weights_verified": False,
            "server_launch_arguments": "UNKNOWN; retain the Windows launcher/server log separately",
            "note": "File hashes identify supplied artifacts, not proof that the server loaded them."}


@contextmanager
def capture_turn(runtime):
    """Observe actual reads/compositions/provider request without extra retrieval.

    The harness runs turns serially in its own fresh data root. These temporary
    method wrappers delegate once and restore even on cancellation or failure.
    HTTP hooks observe the constructed outbound payload, not server receipt.
    """
    from xiyin_runtime import runtime as runtime_module
    from xiyin_runtime.context import RECORDS_PREFIX

    trace = {"checks": {}, "reads": [], "prepared": None, "compositions": [],
             "model_request": None, "wire_requests": [], "raw_generation": "",
             "provider_exception": None, "server_receipt_verified": False,
             "semantic_truth_verified": False}
    prepare, compose, stream = runtime._prepare, runtime._compose, runtime.provider.stream

    def check(name, original):
        def wrapped(*args, **kwargs):
            result = original(*args, **kwargs)
            trace["checks"][name] = {"invoked": True, "triggered": bool(result),
                                      "records": deepcopy(result),
                                      "meaning": "No emitted record is not evidence that a check was unnecessary."}
            return result
        return wrapped

    def read(name, original):
        def wrapped(*args, **kwargs):
            result = original(*args, **kwargs)
            trace["reads"].append({"method": name, "args": deepcopy(args),
                                    "kwargs": deepcopy(kwargs), "returned": deepcopy(result)})
            return result
        return wrapped

    def observed_prepare(*args, **kwargs):
        with ExitStack() as readers:
            for name in ("history", "memories", "search", "action_receipts", "operation_receipts", "list_events"):
                readers.enter_context(patch.object(runtime.store, name, read(name, getattr(runtime.store, name))))
            result = prepare(*args, **kwargs)
        trace["prepared"] = deepcopy(result)
        return result

    def observed_compose(*args, **kwargs):
        result = compose(*args, **kwargs)
        trace["compositions"].append(deepcopy(result))
        return result

    async def observed_stream(messages, cancel, *, budget=None):
        trace["model_request"] = {"messages": deepcopy(messages),
                                   "budget": asdict(budget) if budget else None}
        selected = []
        system = messages[0]["content"]
        if RECORDS_PREFIX in system:
            selected = json.loads(system.split(RECORDS_PREFIX, 1)[1])
        remaining = deepcopy(selected)
        trace["record_projection"] = []
        for index, record in enumerate((trace["prepared"] or {}).get("records", [])):
            included = record in remaining
            if included:
                remaining.remove(record)
            trace["record_projection"].append({"index": index, "record": deepcopy(record),
                                                "in_final_request": included})
        try:
            source = stream(messages, cancel, budget=budget) if runtime._provider_takes_budget else stream(messages, cancel)
            from contextlib import aclosing
            async with aclosing(source):
                async for chunk in source:
                    if isinstance(chunk, str):
                        trace["raw_generation"] += chunk
                    yield chunk
        except Exception as exc:
            # This file stays local to a synthetic run. The public runtime
            # error event is captured separately and must remain sanitized.
            trace["provider_exception"] = {"type": type(exc).__name__, "detail": str(exc)}
            raise

    async def observe_wire(request):
        trace["wire_requests"].append(json.loads(request.content))

    with ExitStack() as stack:
        for name in ("premise_records", "topic_records"):
            stack.enter_context(patch.object(runtime_module, name, check(name, getattr(runtime_module, name))))
        stack.enter_context(patch.object(runtime, "_prepare", observed_prepare))
        stack.enter_context(patch.object(runtime, "_compose", observed_compose))
        stack.enter_context(patch.object(runtime.provider, "stream", observed_stream))
        if hasattr(runtime.provider, "_client"):
            client_factory = runtime.provider._client
            def observed_client(*args, **kwargs):
                client = client_factory(*args, **kwargs)
                client.event_hooks["request"].append(observe_wire)
                return client
            stack.enter_context(patch.object(runtime.provider, "_client", observed_client))
        yield trace
