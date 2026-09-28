"""Temporary cloud comparison (owner request, 2026-09-28): is a large model enough?

The 52 recorded arch01 contexts (plain V4, persona01 A arm: the everyday set
and the eight persona core cases) are sent to a large hosted model through an
OpenAI-compatible chat-completions API, and read against the recorded 4B
replies with the same hints and the same predeclared bar as arch01/arch02.

Test only:
- the runtime is untouched and stays loopback-only; this tool does not use
  its provider;
- only the synthetic test conversations in evidence/ are sent: no ledger,
  memory or production data;
- the key is read from an environment variable and is never written to any
  output; only the API host and model name are recorded.

PowerShell:
    $env:XIYIN_CLOUD_KEY = "<your key>"
    .venv\\Scripts\\python.exe tools\\cloud_probe.py --base-url https://api.example.com/v1 --model <model name> --out C:\\XIYIN\\evidence\\cloud-01
    Remove-Item Env:XIYIN_CLOUD_KEY
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SAMPLES = 2
KEY_ENV = "XIYIN_CLOUD_KEY"


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def chat_url(base_url: str) -> str:
    parts = urlsplit(base_url or "")
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.query:
        raise SystemExit("--base-url must be a plain https URL of an OpenAI-compatible API (no key, no query)")
    base = base_url.rstrip("/")
    return base if base.endswith("/chat/completions") else base + "/chat/completions"


def _sample(client, url, key, model, messages, max_tokens, split_thinking) -> dict:
    import httpx

    payload = {"model": model, "messages": messages, "max_tokens": max_tokens, "stream": False}
    record = {"text": "", "thinking": None, "finish_reason": None, "completion_tokens": None,
              "seconds": None, "error": None}
    started = time.monotonic()
    for attempt in range(4):
        try:
            response = client.post(url, json=payload, headers={"Authorization": f"Bearer {key}"})
        except httpx.HTTPError as exc:
            record["error"] = type(exc).__name__
            time.sleep(2 ** attempt)
            continue
        if response.status_code in (429, 500, 502, 503, 504):
            record["error"] = f"HTTP {response.status_code}"
            time.sleep(2 ** (attempt + 1))
            continue
        if response.status_code != 200:
            record["error"] = f"HTTP {response.status_code}"
            break
        try:
            body = response.json()
            choice = body["choices"][0]
            message = choice.get("message") or {}
            text, inline = split_thinking(message.get("content") or "")
            record.update(text=text, thinking=(message.get("reasoning_content") or inline or None),
                          finish_reason=choice.get("finish_reason"),
                          completion_tokens=(body.get("usage") or {}).get("completion_tokens"), error=None)
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            record["error"] = type(exc).__name__
        break
    record["seconds"] = round(time.monotonic() - started, 3)
    return record


def run(base_url: str, model: str, out: Path, *, key: str, transport=None, progress=True) -> dict:
    import httpx

    pipeline = _load("codex_eval_pipeline", "tools/codex_eval_pipeline.py")
    cp = _load("ceiling_probe", "tools/ceiling_probe.py")
    harness = _load("acceptance_dialogue", "tools/acceptance_dialogue.py")
    url = chat_url(base_url)
    out.mkdir(parents=True, exist_ok=True)
    sources = pipeline._arch_sources(out)
    cases = {case["id"] for case in harness.EVERYDAY_CASES} | set(pipeline.PERSONA_REVIEW_CORE)
    arm = {"host": urlsplit(url).hostname, "model": model, "samples": SAMPLES, "measurement_only": True}
    cloud = {"kind": cp.KIND, "label": "cloud", "arm": arm, "corpus_role": "EVAL_HOLDOUT",
             "training_allowed": False, "turns": []}
    recorded = {"kind": cp.KIND, "label": "recorded4b", "arm": {"source": "persona01 A arm, one sample"},
                "turns": []}
    with httpx.Client(timeout=300.0, trust_env=True, follow_redirects=False, transport=transport) as client:
        for path in sources:
            report = json.loads(path.read_text(encoding="utf-8"))
            for key_name, case_id, index, turn in cp._turns(report, cases):
                plan = turn.get("plan") or {}
                budget = max(plan.get("max_tokens") if type(plan.get("max_tokens")) is int else 512, 1024)
                base = {"key": key_name, "case": case_id, "turn": index, "input": turn.get("input"),
                        "condition": turn.get("condition"), "mode": (turn.get("turn_policy") or {}).get("mode"),
                        "messages": turn["sent_messages"], "original": ""}
                recorded["turns"].append({**base, "samples": [
                    {"text": turn.get("raw_generation") or "", "error": None, "finish_reason": "stop"}]})
                samples = [_sample(client, url, key, model, turn["sent_messages"], budget, cp.split_thinking)
                           for _ in range(SAMPLES)]
                cloud["turns"].append({**base, "samples": samples})
                if progress:
                    print(f"  {key_name:<34} {sum(1 for s in samples if not s['error'])}/{SAMPLES}", flush=True)
    screens = {"recorded4b": cp.screen(recorded), "cloud": cp.screen(cloud)}
    reading = pipeline.arch_reading(screens["recorded4b"], screens["cloud"])
    errors = sum(1 for turn in cloud["turns"] for s in turn["samples"] if s["error"])
    result = {"arm": arm, "screens": screens, "reading": reading, "transport_errors": errors}
    (out / "probe-cloud.json").write_text(json.dumps(cloud, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "cloud-readings.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    _report(out, result)
    with zipfile.ZipFile(out.with_suffix(".zip"), "w", zipfile.ZIP_DEFLATED) as archive:
        for name in ("probe-cloud.json", "cloud-readings.json", "REPORT-DRAFT.md"):
            archive.write(out / name, Path(out.name) / name)
    return result


def _report(out: Path, r: dict) -> None:
    rows = ["| 臂 | 样本 | 编造类 | 身体/过去 | 共同经历 | 机器腔 | 状态回显 | 场景 | 自称活动 | 抛回话头 | 硬提示 | 空回复 |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, s in r["screens"].items():
        f = s["fab_rate"]
        rows.append(f"| {name} | {s['samples']} | {f['fab_any']} | {f['fab_body_past']} | {f['fab_shared_history']} | "
                    f"{f['machine_talk']} | {f['state_echo']} | {f['fab_scene']} | {f['fab_self_activity']} | "
                    f"{s['info_rate']['hands_back']} | {round(1 - (s['hard_clean_rate'] or 0), 3)} | "
                    f"{s['hint_rate']['empty']} |")
    usable = r["transport_errors"] <= 0.1 * r["screens"]["cloud"]["turns"] * SAMPLES
    verdict = ("INVALID(transport errors)" if not usable else
               "LARGE_MODEL_HELPS" if r["reading"]["reading"] == "ARCH_EFFECT" else "NOT_SOLVED_BY_LARGE_MODEL")
    lines = ["# cloud-01 报告草稿（tools/cloud_probe.py，临时云端对照，仅测试）", "",
             f"- 服务：{r['arm']['host']}；模型：{r['arm']['model']}；每轮 {SAMPLES} 个样本；传输错误 {r['transport_errors']}",
             "- 只发送了 evidence/ 里的合成测试对话；密钥没有写入任何文件。", "",
             *rows, "",
             "recorded4b = persona-01 A 臂里 4B 的原始回复（每轮 1 个）。读法与 arch-01/02 相同：编造类或抛回话头降到一半以下，"
             "且硬提示、空回复各不高于 0.03 → 有效。正则提示，需人工核对样本。", "", "```",
             f"CLOUD_VERDICT: {verdict}", f"READING: {r['reading']['reading']}",
             "RUNTIME_CHANGE: NONE", "TRAINING: NOT_AUTHORIZED", "MERGE_STATUS: DO_NOT_MERGE", "```"]
    (out / "REPORT-DRAFT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--base-url", required=True, help="OpenAI-compatible API base, e.g. https://…/v1")
    parser.add_argument("--model", required=True, help="the model name your provider's console shows")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    key = os.environ.get(KEY_ENV, "").strip()
    if not key:
        raise SystemExit(f"set the key in the environment first: $env:{KEY_ENV} = \"<your key>\"")
    result = run(args.base_url, args.model, Path(args.out), key=key)
    print(Path(args.out) / "REPORT-DRAFT.md")
    print(Path(args.out).with_suffix(".zip"))
    return 0 if result["transport_errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
