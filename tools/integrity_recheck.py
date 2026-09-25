"""Re-run the Phase B claim checks over recorded replies, offline.

Two uses:
- validate a --verify-before-release run: its released text must have zero
  closed-class violations;
- measure what an unverified run would have released: the same checks over
  released_text or raw_generation of runs without the hold.

The evidence is rebuilt from what each turn recorded:
- action receipts and the record check, from the records in its system
  message;
- the user's earlier inputs in the case;
- her earlier delivered replies;
- its TurnPolicy.

That is close to, not identical with, the live ledger: memories are not in
the report. Measurement only. It opens no runtime, data root or model.

    python tools\\integrity_recheck.py runs\\a\\dialogue.json runs\\b\\dialogue.json --field released_text --out recheck.json
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from xiyin_runtime.integrity import Evidence, check_reply  # noqa: E402

_RECEIPT = re.compile(r'\{"来源":"动作执行回执"[^{}]*\}')
_PREMISE = re.compile(r'\{"来源":"对本轮说法的记录核对"[^{}]*\}')
_OPERATIONS = {"写入文件": "write_text", "读取文件": "read_text"}


def evidence_for(turn: dict, earlier_inputs: list[str], own_words: list[str]) -> Evidence:
    messages = turn.get("sent_messages") or []
    system = messages[0]["content"] if messages else ""
    receipts = []
    for match in _RECEIPT.finditer(system):
        record = json.loads(match[0])
        operation = _OPERATIONS.get(record.get("动作"))
        if operation and "已执行" in record.get("结果", ""):
            receipts.append({"operation": operation, "status": "success",
                             "evidence": {"path": record.get("对象", "")}})
    premise = None
    found = _PREMISE.search(system)
    if found:
        try:
            premise = json.loads(found[0])
        except ValueError:
            premise = None
    policy = turn.get("turn_policy") or {}
    return Evidence(action_receipts=tuple(receipts), premise=premise, own_words=tuple(own_words),
                    scoped_texts=tuple((*earlier_inputs, turn.get("input", ""))),
                    user_text=turn.get("input", ""), recent_user_texts=tuple(earlier_inputs[-4:]),
                    mode=policy.get("mode", "conversation"),
                    allow_code_literals=bool(policy.get("allow_code_literals")))


def recheck(report: dict, field: str = "released_text") -> dict:
    counts, flagged, turns, flagged_turns = Counter(), [], 0, 0
    for case in report.get("cases", []):
        earlier, own = [], []
        for index, turn in enumerate(case.get("turns", []), 1):
            text = turn.get(field) or ""
            if turn.get("sent_messages") and text.strip() and turn.get("status") != "abstained":
                turns += 1
                violations = check_reply(text, evidence_for(turn, earlier, own))
                flagged_turns += bool(violations)
                for item in violations:
                    counts[item.kind] += 1
                    flagged.append({"turn": f"{case['id']}#{index}", **item.to_dict()})
            earlier.append(turn.get("input", ""))
            if turn.get("status") == "completed":
                own.append(turn.get("released_text") or "")
    return {"label": report.get("label"), "field": field, "turns_checked": turns,
            "turns_flagged": flagged_turns, "by_kind": dict(counts), "flagged": flagged,
            "verify_before_release": bool(report.get("verify_before_release"))}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("reports", nargs="+")
    parser.add_argument("--field", default="released_text", choices=("released_text", "raw_generation"))
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    results = [recheck(json.loads(Path(path).read_text(encoding="utf-8")), args.field) for path in args.reports]
    text = json.dumps(results, ensure_ascii=False, indent=1)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    for result in results:
        print(f"{result['label']}: {result['turns_flagged']}/{result['turns_checked']} flagged {result['by_kind']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
