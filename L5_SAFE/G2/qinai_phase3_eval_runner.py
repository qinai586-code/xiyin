# -*- coding: utf-8 -*-
"""QINAI Phase 3 eval runner.

Default mode is a no-send dry run. Real L2 sending is available only when the
caller explicitly selects send mode and supplies the owner approval flag.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from qinai_l2_eval_helpers import (
    decode_loopback_channel_arg,
    get_l2_chat_channel_arg,
    read_fresh_l2_heartbeat,
    send_l2_chat_request,
)
import xiyin_paths as _paths
CORE16_PATH = _paths.project_root() / "L5_SAFE/L5_DATA/EVAL_SETS/QINAI_CORE_16_EVAL.jsonl"
DEFAULT_OUTPUT_DIR = _paths.project_root() / "L5_SAFE/G2/reports"
DEFAULT_MODEL_PROFILE = "production_swallow_8b"
WAIT_CHECK_PATH = _paths.resolve_path("data") / "wait_check"
ROUTE_DRY_RUN = "dry_run_no_send"
ROUTE_L2_INTERACTIVE = "launcher_l2_chat_channel_interactive"
DRY_RUN_REJECTION_REASON = "DRY_RUN_NO_MODEL_EVAL"
C4_STATUS_NOT_EXPOSED = "not_exposed_by_current_channel"
L2_PREFLIGHT_MAX_ATTEMPTS = 3
L2_PREFLIGHT_RETRY_DELAY_SECONDS = 1.0

APPROVED_LAUNCHER_HELPERS = (
    "read_fresh_l2_heartbeat",
    "get_l2_chat_channel_arg",
    "decode_loopback_channel_arg",
    "send_l2_chat_request",
)

REQUIRED_PROBE_FIELDS = ("id", "prompt", "expected_language")
REQUIRED_RECORD_FIELDS = (
    "id",
    "model_profile",
    "raw_prompt_loaded_from_jsonl",
    "prompt_sent_to_L2",
    "prompt_exact_match",
    "prompt_utf8_sha256_loaded",
    "prompt_utf8_sha256_sent",
    "visible_reply",
    "expected_language",
    "language_ok",
    "p0_pass",
    "p0_failures",
    "p1_scores",
    "p2_notes",
    "route_used",
    "latency_ms",
    "error_state",
    "accepted_as_evidence",
    "evidence_rejection_reason",
    "c4_fallback_or_rewrite_status",
    "wait_check_files_created",
    "source_log_reference",
)

MOJIBAKE_MARKERS = (
    "\ufffd",
    "????",
    "\u00c3",
    "\u00e3",
    "\u00e4\u00b8",
    "\u00e7",
    "\u00ef\u00bc",
)


class EvalRunnerError(RuntimeError):
    """Base class for runner hygiene failures."""


class PromptHygieneError(EvalRunnerError):
    """Raised when loaded and sent prompt text would differ or is corrupted."""


class SendModeNotApproved(EvalRunnerError):
    """Raised when a caller attempts sending without the approval flag."""


class L2RouteError(EvalRunnerError):
    """Raised when the launcher/L2 route is not ready or invalid."""


def utc_timestamp() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def utf8_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest().upper()


def has_prompt_corruption(text: str) -> bool:
    return any(marker in text for marker in MOJIBAKE_MARKERS)


def read_eval_jsonl(path: Path, expected_count: int) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise EvalRunnerError(f"JSONL parse failed at line {line_number}: {exc}") from exc
            missing = [field for field in REQUIRED_PROBE_FIELDS if field not in obj]
            if missing:
                raise EvalRunnerError(f"Probe line {line_number} missing fields: {missing}")
            records.append(obj)
    if len(records) != expected_count:
        raise EvalRunnerError(
            f"Expected exactly {expected_count} eval probe(s), found {len(records)}"
        )
    return records


def _prompt_fields(probe: Dict[str, Any]) -> Dict[str, Any]:
    raw_prompt = str(probe["prompt"])
    prompt_sent = raw_prompt
    exact_match = raw_prompt == prompt_sent
    if not exact_match:
        raise PromptHygieneError(f"Prompt mismatch for {probe.get('id')}")
    if has_prompt_corruption(raw_prompt):
        raise PromptHygieneError(f"Prompt corruption detected for {probe.get('id')}")
    return {
        "raw_prompt_loaded_from_jsonl": raw_prompt,
        "prompt_sent_to_L2": prompt_sent,
        "prompt_exact_match": exact_match,
        "prompt_utf8_sha256_loaded": utf8_sha256(raw_prompt),
        "prompt_utf8_sha256_sent": utf8_sha256(prompt_sent),
    }


def _base_record(probe: Dict[str, Any], model_profile: str, route_used: str) -> Dict[str, Any]:
    record: Dict[str, Any] = {
        "id": str(probe["id"]),
        "model_profile": model_profile,
        **_prompt_fields(probe),
        "visible_reply": None,
        "expected_language": str(probe["expected_language"]),
        "language_ok": None,
        "p0_pass": "not_scored",
        "p0_failures": "post_processing_pending",
        "p1_scores": "post_processing_pending",
        "p2_notes": "post_processing_pending",
        "route_used": route_used,
        "latency_ms": 0,
        "error_state": None,
        "accepted_as_evidence": False,
        "evidence_rejection_reason": None,
        "c4_fallback_or_rewrite_status": C4_STATUS_NOT_EXPOSED,
        "wait_check_files_created": [],
        "source_log_reference": None,
    }
    _assert_record_schema(record)
    return record


def make_no_send_record(probe: Dict[str, Any], model_profile: str) -> Dict[str, Any]:
    record = _base_record(probe, model_profile, ROUTE_DRY_RUN)
    record["evidence_rejection_reason"] = DRY_RUN_REJECTION_REASON
    return record


def _assert_record_schema(record: Dict[str, Any]) -> None:
    missing_fields = [field for field in REQUIRED_RECORD_FIELDS if field not in record]
    extra_fields = [field for field in record if field not in REQUIRED_RECORD_FIELDS]
    if missing_fields or extra_fields:
        raise EvalRunnerError(
            f"Internal schema error, missing={missing_fields}, extra={extra_fields}"
        )


def build_no_send_records(probes: Iterable[Dict[str, Any]], model_profile: str) -> List[Dict[str, Any]]:
    return [make_no_send_record(probe, model_profile) for probe in probes]


def preflight_validate_probes(probes: Sequence[Dict[str, Any]]) -> None:
    for probe in probes:
        _prompt_fields(probe)


def write_jsonl(path: Path, records: Sequence[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def write_markdown_summary(path: Path, records: Sequence[Dict[str, Any]], model_profile: str, route: str) -> None:
    lines = [
        "# QINAI Phase 3 Eval Runner Summary",
        "",
        f"Generated UTC: {utc_timestamp()}",
        f"Mode: {route}",
        f"Model profile metadata: `{model_profile}`",
        "",
        "| id | expected_language | prompt_exact_match | loaded_sha256 | sent_sha256 | accepted |",
        "|---|---|---:|---|---|---:|",
    ]
    for record in records:
        lines.append(
            "| {id} | {lang} | {match} | {loaded} | {sent} | {accepted} |".format(
                id=record["id"],
                lang=record["expected_language"],
                match=str(record["prompt_exact_match"]).lower(),
                loaded=record["prompt_utf8_sha256_loaded"],
                sent=record["prompt_utf8_sha256_sent"],
                accepted=str(record["accepted_as_evidence"]).lower(),
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_outputs(output_dir: Path, prefix: str, records: Sequence[Dict[str, Any]], model_profile: str, route: str) -> Dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = utc_timestamp()
    jsonl_path = output_dir / f"{prefix}_RESULTS_{stamp}.jsonl"
    report_path = output_dir / f"{prefix}_REPORT_{stamp}.md"
    write_jsonl(jsonl_path, records)
    write_markdown_summary(report_path, records, model_profile, route)
    return {"jsonl_path": str(jsonl_path), "report_path": str(report_path)}


def run_dry_run(args: argparse.Namespace) -> int:
    probes = read_eval_jsonl(Path(args.eval_set), args.expected_count)
    records = build_no_send_records(probes, args.model_profile)

    output_payload: Dict[str, Any] = {
        "status": "DRY_RUN_NO_MODEL_EVAL",
        "records": len(records),
        "model_profile": args.model_profile,
        "route_used": ROUTE_DRY_RUN,
        "outputs_written": False,
    }

    if args.write_output:
        output_payload.update(
            write_outputs(
                Path(args.output_dir),
                "QINAI_PHASE3_DRY_RUN",
                records,
                args.model_profile,
                ROUTE_DRY_RUN,
            )
        )
        output_payload["outputs_written"] = True

    print(json.dumps(output_payload, ensure_ascii=False, sort_keys=True))
    return 0


def load_l2_eval_helpers() -> Dict[str, Any]:
    helpers: Dict[str, Any] = {
        "read_fresh_l2_heartbeat": read_fresh_l2_heartbeat,
        "get_l2_chat_channel_arg": get_l2_chat_channel_arg,
        "decode_loopback_channel_arg": decode_loopback_channel_arg,
        "send_l2_chat_request": send_l2_chat_request,
    }
    for name in APPROVED_LAUNCHER_HELPERS:
        helper = helpers.get(name)
        if not callable(helper):
            raise L2RouteError(f"L2 eval helper unavailable: {name}")
    return helpers


def resolve_l2_channel(helpers: Dict[str, Any]) -> str:
    heartbeat, issue = helpers["read_fresh_l2_heartbeat"]()
    if issue is not None:
        raise L2RouteError(f"L2 heartbeat issue: {issue}")
    if not isinstance(heartbeat, dict):
        raise L2RouteError("L2 heartbeat is missing or invalid.")
    if not heartbeat.get("ready"):
        raise L2RouteError("L2 heartbeat ready=false.")
    if str(heartbeat.get("stage") or "").strip() != "ready":
        raise L2RouteError(f"L2 heartbeat stage is not ready: {heartbeat.get('stage')}")
    if not heartbeat.get("chat_ready"):
        raise L2RouteError("L2 chat_ready=false.")
    if heartbeat.get("chat_busy"):
        raise L2RouteError("L2 chat channel is busy.")
    channel_arg = helpers["get_l2_chat_channel_arg"](heartbeat)
    if not channel_arg:
        raise L2RouteError("L2 chat channel is unavailable.")
    helpers["decode_loopback_channel_arg"](channel_arg)
    return channel_arg


def resolve_l2_channel_with_bounded_retry(helpers: Dict[str, Any]) -> str:
    last_error: Optional[L2RouteError] = None
    for attempt in range(1, L2_PREFLIGHT_MAX_ATTEMPTS + 1):
        try:
            return resolve_l2_channel(helpers)
        except L2RouteError as exc:
            last_error = exc
            if attempt < L2_PREFLIGHT_MAX_ATTEMPTS:
                time.sleep(L2_PREFLIGHT_RETRY_DELAY_SECONDS)
    raise L2RouteError(
        f"L2 startup preflight failed after {L2_PREFLIGHT_MAX_ATTEMPTS} attempts: {last_error}"
    )


def list_wait_check_file_paths() -> Set[str]:
    if not WAIT_CHECK_PATH.exists():
        return set()
    return {str(path) for path in WAIT_CHECK_PATH.iterdir() if path.is_file()}


def make_send_record(
    probe: Dict[str, Any],
    model_profile: str,
    response: Dict[str, Any],
    latency_ms: int,
    wait_delta: Sequence[str],
) -> Dict[str, Any]:
    record = _base_record(probe, model_profile, ROUTE_L2_INTERACTIVE)
    ok = bool(response.get("ok"))
    reply = response.get("reply") if ok else None
    record["visible_reply"] = str(reply) if reply is not None else None
    record["latency_ms"] = latency_ms
    record["wait_check_files_created"] = list(wait_delta)
    record["accepted_as_evidence"] = bool(ok and reply is not None)
    if record["accepted_as_evidence"]:
        record["evidence_rejection_reason"] = None
    else:
        error = str(response.get("error") or "L2_RESPONSE_NOT_OK")
        record["error_state"] = error
        record["evidence_rejection_reason"] = error
    _assert_record_schema(record)
    return record


def run_send(args: argparse.Namespace) -> int:
    if not args.owner_approved_send:
        raise SendModeNotApproved("Send mode requires --owner-approved-send.")

    probes = read_eval_jsonl(Path(args.eval_set), args.expected_count)
    preflight_validate_probes(probes)
    helpers = load_l2_eval_helpers()
    channel_arg = resolve_l2_channel_with_bounded_retry(helpers)
    records: List[Dict[str, Any]] = []

    for probe in probes:
        wait_before = list_wait_check_file_paths()
        started = time.perf_counter()
        response = helpers["send_l2_chat_request"](
            channel_arg,
            str(probe["prompt"]),
            source="interactive",
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        if not isinstance(response, dict):
            raise L2RouteError("L2 chat channel returned a non-dict response.")
        wait_after = list_wait_check_file_paths()
        wait_delta = sorted(wait_after - wait_before)
        records.append(make_send_record(probe, args.model_profile, response, latency_ms, wait_delta))

    output_payload: Dict[str, Any] = {
        "status": "SEND_COMPLETED",
        "records": len(records),
        "model_profile": args.model_profile,
        "route_used": ROUTE_L2_INTERACTIVE,
        "outputs_written": False,
    }

    if args.write_output:
        output_payload.update(
            write_outputs(
                Path(args.output_dir),
                "QINAI_PHASE3_SEND",
                records,
                args.model_profile,
                ROUTE_L2_INTERACTIVE,
            )
        )
        output_payload["outputs_written"] = True

    print(json.dumps(output_payload, ensure_ascii=False, sort_keys=True))
    return 0


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="QINAI Phase 3 eval runner")
    parser.add_argument("--mode", choices=("dry-run", "send"), default="dry-run")
    parser.add_argument("--eval-set", default=str(CORE16_PATH))
    parser.add_argument("--expected-count", type=int, choices=(16, 1), default=16)
    parser.add_argument("--model-profile", default=DEFAULT_MODEL_PROFILE)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument(
        "--write-output",
        action="store_true",
        help="Write JSONL/Markdown outputs. Use send outputs only after owner approval.",
    )
    parser.add_argument(
        "--owner-approved-send",
        action="store_true",
        help="Required with --mode send. Does not change the default dry-run mode.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        if args.mode == "dry-run":
            return run_dry_run(args)
        return run_send(args)
    except SendModeNotApproved as exc:
        print(json.dumps({"status": "SEND_MODE_NOT_APPROVED", "error": str(exc)}), file=sys.stderr)
        return 2
    except EvalRunnerError as exc:
        print(json.dumps({"status": "EVALUATOR_HYGIENE_FAILURE", "error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


