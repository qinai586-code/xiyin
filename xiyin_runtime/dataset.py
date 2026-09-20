"""Explicit local exports with provenance; generated answers are not gold labels."""
import hashlib
import json
from pathlib import Path


def export_dataset(store, directory, *, session_id="owner", scope="private"):
    destination = Path(directory)
    if destination.exists() or destination.is_symlink() or not destination.parent.is_dir():
        raise ValueError("Dataset export requires a new directory under an existing parent")
    events = store.list_events(session_id, scope)
    rows = []
    pending = None
    for event in events:
        if event["kind"] == "user" and event["status"] in {"complete", "completed"}:
            pending = event
        elif event["kind"] == "assistant":
            if pending and pending["request_id"] and pending["request_id"] == event["request_id"] and event["status"] in {"complete", "completed"}:
                rows.append({"messages": [{"role": "user", "content": pending["content"]},
                                           {"role": "assistant", "content": event["content"]}],
                             "source_event_ids": [pending["id"], event["id"]], "scope": scope,
                             "session_id": session_id, "origin": "recorded_model_output",
                             "quality_label": "unreviewed", "eligible_for_training": False})
            pending = None
    payload = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows).encode("utf-8")
    destination.mkdir()
    (destination / "candidates.jsonl").write_bytes(payload)
    manifest = {"schema": "xiyin.dataset.candidates.v1", "rows": len(rows), "scope": scope,
                "sha256": hashlib.sha256(payload).hexdigest(), "uploaded": False,
                "training_started": False, "quality": "unreviewed; filter and independently evaluate before training"}
    (destination / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    store.append_event("dataset_export", manifest, session_id=session_id, scope=scope,
                       origin="tool_result", status="verified_success")
    return manifest
