"""Local, quarantined capture of candidate data from blind reviews and owner edits.

Owner authorisation (2026-09-24): LOCAL_CANDIDATE_DATA_COLLECTION_ONLY.
- Only RAW_CANDIDATE records are created. Nothing is promoted, trained or exported.
- The current 81-turn acceptance corpus is EVAL_HOLDOUT.
- No external upload; no production change.

What this tool is:
- a recorder of explicit review evidence (a blind package, its key, the run reports and the
  owner's judgments) and of explicit owner-edited replies;
- stdlib only; it opens no network connection and imports nothing that trains a model.

What it is not:
- a reader of the ledger, memory or any conversation it was not handed;
- a promotion path (REVIEWED, TRAINING_CANDIDATE and OWNER_APPROVED are listed but never
  written);
- a training-set exporter.

The SFT and DPO candidate stores exist only as empty files that fix the layout.

Store layout (one directory, outside the repository and the XIYIN data root):

    manifest.json            schema, authorisation, lifecycle, file roles
    eval_holdout.jsonl       judgments and edits about acceptance-corpus cases
    raw_preferences.jsonl    RAW_CANDIDATE preferences from non-corpus review material
    raw_edits.jsonl          RAW_CANDIDATE owner edits of non-corpus replies
    rejected_failures.jsonl  non-preferred responses and failure labels (negative evidence)
    sft_candidates.jsonl     empty: promotion not authorised
    dpo_candidates.jsonl     empty: promotion not authorised
    deletions.jsonl          tombstones (id, time, reason), no content

Usage:

    python tools/candidate_data.py init   --store D:/xiyin-candidates
    python tools/candidate_data.py ingest-review --store D:/xiyin-candidates \\
        --review reviewer/blind-review.json --key keys/blind-key.json \\
        --judgments owner-judgments.json --reports dialogue-a.json dialogue-b.json
    python tools/candidate_data.py ingest-edits --store D:/xiyin-candidates --edits owner-edits.json \\
        [--reports dialogue-a.json]
    python tools/candidate_data.py status --store D:/xiyin-candidates
    python tools/candidate_data.py forget --store D:/xiyin-candidates --id <record id> --reason "owner request"

Input formats:

    judgments: {"judgments": [{"id": "P5_casual_sharing#1", "preferred": "A" | "B" | ... | "tie" | "none",
                               "reason": "...", "labels": {"A": {...}, "B": {...}}}]}
    edits:     {"edits": [{"case_id": "P5_casual_sharing", "turn": 1, "report": "<label>",   # optional
                           "input": "...", "original": "...", "edited": "...", "reason": "..."}]}
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import xiyin_paths  # noqa: E402

SCHEMA = "xiyin.candidate.v1"
AUTHORISATION = "LOCAL_CANDIDATE_DATA_COLLECTION_ONLY"
LIFECYCLE = ("RAW_CANDIDATE", "REVIEWED", "TRAINING_CANDIDATE", "OWNER_APPROVED")
CREATED_STATE = "RAW_CANDIDATE"  # the only state this tool writes
FILES = {
    "eval_holdout": "eval_holdout.jsonl",
    "raw_preferences": "raw_preferences.jsonl",
    "raw_edits": "raw_edits.jsonl",
    "rejected_failures": "rejected_failures.jsonl",
    "sft_candidates": "sft_candidates.jsonl",
    "dpo_candidates": "dpo_candidates.jsonl",
    "deletions": "deletions.jsonl",
}
WRITABLE = {"eval_holdout", "raw_preferences", "raw_edits", "rejected_failures", "deletions"}
# Unset until a future review; a stylistic winner that fails any of these can
# never become a positive example.
INTEGRITY_CHECKS = ("factual_correctness", "no_fabricated_memory_or_experience", "no_unsupported_action_claim",
                    "identity_and_relationship", "privacy_and_scope", "speaker_attribution",
                    "no_internal_prompt_leak")
_KEY = re.compile(r"[\W_]+")
_PARAPHRASE_RATIO = 0.8


class CandidateDataError(RuntimeError):
    pass


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _norm(text: str) -> str:
    return _KEY.sub("", (text or "").casefold())


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record_id(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:32]


def _corpus():
    """The acceptance corpus: case ids and normalised inputs. Always EVAL_HOLDOUT."""
    from tools.acceptance_dialogue import CASES

    return ({case["id"] for case in CASES},
            [_norm(turn["text"]) for case in CASES for turn in case["turns"]])


def is_eval_holdout(text: str | None, case_id: str | None = None) -> bool:
    """A corpus case, its exact input, or a near paraphrase of one stays out of training."""
    ids, inputs = _corpus()
    if case_id and case_id in ids:
        return True
    key = _norm(text or "")
    if not key:
        return False
    return any(key == item or difflib.SequenceMatcher(None, key, item).ratio() >= _PARAPHRASE_RATIO
               for item in inputs)


def _check_store_location(store: Path) -> Path:
    """Refuse the repository (commit risk) and the XIYIN data root (production memory)."""
    resolved = store.resolve()
    forbidden = [xiyin_paths.project_root().resolve()]
    try:
        forbidden.append(xiyin_paths.data_root().resolve())
    except Exception:
        pass  # no configured data root on this machine: nothing to collide with
    for root in forbidden:
        if resolved == root or root in resolved.parents:
            raise CandidateDataError(f"store must be outside {root}")
    return resolved


def _open_store(store: str, *, create: bool = False) -> Path:
    root = _check_store_location(Path(store))
    manifest = root / "manifest.json"
    if create:
        root.mkdir(parents=True, exist_ok=True)
        if not manifest.exists():
            manifest.write_text(json.dumps({
                "schema": SCHEMA, "authorisation": AUTHORISATION, "created_at": _now(),
                "lifecycle": list(LIFECYCLE), "writable_states": [CREATED_STATE],
                "files": FILES, "training_allowed_by_this_tool": False,
                "note": "Local only. No promotion, training, export or upload is implemented.",
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        for name in FILES.values():
            (root / name).touch(exist_ok=True)
    elif not manifest.is_file():
        raise CandidateDataError("not a candidate store; run init first")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA or data.get("authorisation") != AUTHORISATION:
        raise CandidateDataError("store manifest does not match this tool")
    return root


def _read(root: Path, store_name: str) -> list[dict]:
    path = root / FILES[store_name]
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _append(root: Path, store_name: str, record: dict) -> bool:
    """Append once; an id already present is not written again."""
    if store_name not in WRITABLE:
        raise CandidateDataError(f"{store_name} is not writable under {AUTHORISATION}")
    if record.get("lifecycle_state", CREATED_STATE) != CREATED_STATE or record.get("training_allowed", False):
        raise CandidateDataError("only RAW_CANDIDATE records with training_allowed=false may be written")
    if any(item.get("id") == record["id"] for item in _read(root, store_name)):
        return False
    with (root / FILES[store_name]).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return True


def _report_provenance(report: dict) -> dict:
    model = report.get("model", {})
    server = (model.get("server_sampling") or {})
    identity = model.get("identity") or {}
    return {"label": report.get("label"), "code_revision": report.get("code_revision"),
            "started_at": report.get("started_at"), "persona_projection": report.get("persona_projection"),
            "model_file": (identity.get("file") or {}).get("name"),
            "model_sha256": (identity.get("file") or {}).get("sha256"),
            "matches_manifest": identity.get("matches_manifest"),
            "server": server.get("server"), "server_sampling": server.get("settings"),
            "sent_sampling": model.get("sent_sampling") or {}}


def _turn(report: dict, case_id: str, index: int) -> dict:
    for case in report.get("cases", []):
        if case["id"] == case_id:
            return case["turns"][index]
    raise CandidateDataError(f"case {case_id} not in report {report.get('label')}")


def _response(letter: str, report: dict, turn: dict) -> dict:
    plan = turn.get("plan") or {}
    return {"letter": letter, "arm_label": report.get("label"),
            "persona_projection": plan.get("persona_projection") or report.get("persona_projection"),
            "persona_sha256": plan.get("persona_sha256"), "status": turn.get("status"),
            "guard_reason": turn.get("guard_reason"), "request_id": turn.get("request_id"),
            "raw_generation": turn.get("raw_generation"), "released_text": turn.get("released_text"),
            "released_segments": turn.get("released_segments")}


def ingest_review(store, review_path, key_path, judgments_path, report_paths) -> dict:
    root = _open_store(store)
    review = json.loads(Path(review_path).read_text(encoding="utf-8"))
    key = json.loads(Path(key_path).read_text(encoding="utf-8"))
    judgments = json.loads(Path(judgments_path).read_text(encoding="utf-8")).get("judgments", [])
    reports = {}
    for path in report_paths:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        reports[data.get("label")] = data
    items = {item["id"]: item for item in review.get("items", [])}
    sources = {"review_file_sha256": _sha256_file(Path(review_path)), "key_sha256": _sha256_file(Path(key_path)),
               "judgments_sha256": _sha256_file(Path(judgments_path))}
    counts = {"eval_holdout": 0, "raw_preferences": 0, "rejected_failures": 0, "skipped": 0}
    for judgment in judgments:
        item = items.get(judgment.get("id"))
        mapping = key.get("key", {}).get(judgment.get("id"))
        preferred = judgment.get("preferred")
        if item is None or mapping is None or not (preferred in mapping or preferred in {"tie", "none"}):
            counts["skipped"] += 1
            continue
        case_id, _, number = item["id"].rpartition("#")
        index = int(number) - 1
        responses = []
        for letter, label in sorted(mapping.items()):
            report = reports.get(label)
            if report is None:
                raise CandidateDataError(f"report for arm {label} was not supplied")
            responses.append(_response(letter, report, _turn(report, case_id, index)))
        first = _turn(reports[mapping[sorted(mapping)[0]]], case_id, index)
        holdout = is_eval_holdout(item.get("input"), case_id)
        record = {
            "schema": SCHEMA, "kind": "preference", "lifecycle_state": CREATED_STATE,
            "source_role": "eval_holdout" if holdout else "review", "training_allowed": False,
            "id": _record_id("preference", item["id"], sorted(mapping.items()), preferred),
            "created_at": _now(),
            "context": {"item_id": item["id"], "case_id": case_id, "turn_index": index + 1,
                        "input": item.get("input"), "scope": item.get("scope"), "condition": item.get("condition"),
                        "read": item.get("read"),
                        "sent_messages_sha256": hashlib.sha256(json.dumps(
                            first.get("sent_messages"), ensure_ascii=False, sort_keys=True).encode()).hexdigest()},
            "responses": responses,
            "preference": {"preferred": preferred, "reason": judgment.get("reason"),
                           "labels": judgment.get("labels")},
            "provenance": {"reports": [_report_provenance(reports[label]) for _, label in sorted(mapping.items())],
                           **sources},
            "integrity_review": {name: None for name in INTEGRITY_CHECKS},
        }
        target = "eval_holdout" if holdout else "raw_preferences"
        if _append(root, target, record):
            counts[target] += 1
        if preferred not in {"tie", "none"}:
            for response in responses:
                if response["letter"] == preferred:
                    continue
                rejected = {"schema": SCHEMA, "kind": "rejected_response", "lifecycle_state": CREATED_STATE,
                            "source_role": record["source_role"], "training_allowed": False,
                            "id": _record_id("rejected", record["id"], response["letter"]),
                            "created_at": _now(), "preference_id": record["id"], "context": record["context"],
                            "response": response,
                            "failure_labels": (judgment.get("labels") or {}).get(response["letter"])}
                if _append(root, "rejected_failures", rejected):
                    counts["rejected_failures"] += 1
    return counts


def ingest_edits(store, edits_path, report_paths=()) -> dict:
    root = _open_store(store)
    edits = json.loads(Path(edits_path).read_text(encoding="utf-8")).get("edits", [])
    reports = {}
    for path in report_paths:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        reports[data.get("label")] = data
    counts = {"eval_holdout": 0, "raw_edits": 0, "skipped": 0}
    for edit in edits:
        original, edited = edit.get("original"), edit.get("edited")
        if not isinstance(original, str) or not isinstance(edited, str) or not edited.strip():
            counts["skipped"] += 1
            continue
        provenance = _report_provenance(reports[edit["report"]]) if edit.get("report") in reports else None
        holdout = is_eval_holdout(edit.get("input"), edit.get("case_id"))
        record = {
            "schema": SCHEMA, "kind": "owner_edit", "lifecycle_state": CREATED_STATE,
            "source_role": "eval_holdout" if holdout else "owner_edit", "training_allowed": False,
            "id": _record_id("edit", edit.get("case_id"), edit.get("turn"), edit.get("input"), original, edited),
            "created_at": _now(),
            "context": {"case_id": edit.get("case_id"), "turn_index": edit.get("turn"), "input": edit.get("input")},
            "original": original, "edited": edited,
            "diff": "\n".join(difflib.unified_diff(original.splitlines(), edited.splitlines(),
                                                   "original", "edited", lineterm="")),
            "reason": edit.get("reason"), "provenance": provenance,
            "integrity_review": {name: None for name in INTEGRITY_CHECKS},
        }
        target = "eval_holdout" if holdout else "raw_edits"
        if _append(root, target, record):
            counts[target] += 1
    return counts


def status(store) -> dict:
    root = _open_store(store)
    result = {}
    for name in FILES:
        records = _read(root, name)
        states = {}
        for record in records:
            states[record.get("lifecycle_state", "-")] = states.get(record.get("lifecycle_state", "-"), 0) + 1
        result[name] = {"records": len(records), "states": states,
                        "training_allowed": sum(1 for record in records if record.get("training_allowed"))}
    return result


def forget(store, record_id: str, reason: str) -> int:
    """Remove every record with this id (or referring to it); keep only a tombstone."""
    root = _open_store(store)
    removed = 0
    for name in FILES:
        if name == "deletions":
            continue
        path = root / FILES[name]
        kept = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("id") == record_id or record.get("preference_id") == record_id:
                removed += 1
            else:
                kept.append(line)
        path.write_text("".join(item + "\n" for item in kept), encoding="utf-8")
    with (root / FILES["deletions"]).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"id": record_id, "deleted_at": _now(), "reason": reason, "records_removed": removed},
                                ensure_ascii=False) + "\n")
    return removed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "status"):
        commands.add_parser(name).add_argument("--store", required=True)
    review = commands.add_parser("ingest-review")
    review.add_argument("--store", required=True)
    review.add_argument("--review", required=True)
    review.add_argument("--key", required=True)
    review.add_argument("--judgments", required=True)
    review.add_argument("--reports", nargs="+", required=True)
    edits = commands.add_parser("ingest-edits")
    edits.add_argument("--store", required=True)
    edits.add_argument("--edits", required=True)
    edits.add_argument("--reports", nargs="*", default=())
    drop = commands.add_parser("forget")
    drop.add_argument("--store", required=True)
    drop.add_argument("--id", required=True)
    drop.add_argument("--reason", required=True)
    args = parser.parse_args(argv)
    if args.command == "init":
        _open_store(args.store, create=True)
        result = status(args.store)
    elif args.command == "status":
        result = status(args.store)
    elif args.command == "ingest-review":
        result = ingest_review(args.store, args.review, args.key, args.judgments, args.reports)
    elif args.command == "ingest-edits":
        result = ingest_edits(args.store, args.edits, args.reports)
    else:
        result = {"removed": forget(args.store, args.id, args.reason)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
