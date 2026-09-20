"""Deterministic evidence checks that put the real record in front of XIYIN.

A warning in the character prompt tells her not to invent experiences; it does
not tell her what is actually stored. These projections answer that for the
topic the owner raised: what the ledger holds, and — just as important — what
it does not. Absence is reported as absence and never becomes an experience.

Nothing here writes, rewrites or scores records. It reads already scoped rows
and projects them as conversation material, like ``context.retrieved_record``.
"""
from __future__ import annotations

import json
import re


# The claim must carry a past marker. "你说呢" and "你说吧" are not assertions
# about an earlier turn, so a bare 说 never triggers the check.
_PRIOR_CLAIM = re.compile(
    r"(?:你|妳|栖音)\s*(?:刚才|刚刚|之前|先前|上次|上回|昨天|早些时候|方才)?\s*"
    r"(?:不是)?\s*(?:说过|讲过|提过|提到过|告诉过|答应过|承诺过|保证过|写过|"
    r"(?:刚才|刚刚|之前|先前|上次|上回|昨天|方才)\s*(?:说|讲|提|告诉|答应|承诺|保证|写))|"
    r"(?:我们|咱们)\s*(?:之前|上次|上回|曾经|一起)?\s*"
    r"(?:聊过|说过|讨论过|玩过|做过|约好|约定过|一起.{0,4}过)")
_QUOTED = re.compile(r"[「『“\"']([^」』”\"'\n]{2,120})[」』”\"']")
_AFTER_VERB = re.compile(
    r"(?:说过|讲过|提过|提到过|告诉过我|答应过|承诺过|保证过|说|讲|提到|告诉我)\s*"
    r"[，,：:]?\s*(.{2,120}?)(?:[。？！?!\n]|$)")

_QINAI = re.compile(r"祈奈|qinai", re.I)
_BACKGROUND = re.compile(
    r"(?:刚才|刚刚|这段时间|这几天|这阵子|我不在|不在的时候|没在的时候|离开的时候|"
    r"睡(?:觉|着)的时候|昨晚|后台|背着我|自己一个人|一个人的时候)"
    r".{0,8}?(?:在)?\s*(?:做|干|忙|玩|学|看|想|研究|练)|"
    r"(?:做|干|忙|玩|学|研究|练)了(?:些)?什么")
_PREFERENCE = re.compile(r"喜欢|偏好|爱好|最爱|讨厌|不喜欢|兴趣|口味|擅长")

_ACTION_LABELS = {"read_text": "读取文件", "write_text": "写入文件", "click": "点击",
                  "key_down": "按下按键", "key_up": "松开按键"}
_ACTION_OUTCOMES = {
    ("success", True): "已执行并通过独立校验",
    ("failure", True): "已执行，但校验未达成",
    ("failure", False): "没有执行（在派发前被拒绝）",
    ("unknown", True): "已派发，结果未能确认",
    ("unknown", False): "没有确认是否派发，结果未知",
    ("cancelled", True): "已派发后取消，结果未知",
    ("cancelled", False): "在执行前取消，没有改动",
}


def _brief(value, limit=160):
    text = str(value).strip().replace("\n", " ")
    return text if len(text) <= limit else text[:limit] + "…"


def action_receipt_record(receipt: dict) -> dict[str, str] | None:
    """Project one already scoped action receipt for conversation.

    Failure 3 in the Windows report — denying a file write that had actually
    been verified — was possible because ``retrieved_record`` drops every
    JSON-shaped tool result, so no action receipt could reach the prompt at
    all. This is the missing adapter, and it keeps dispatch separate from
    completion instead of collapsing both into "failed".
    """
    content = receipt.get("content")
    if not isinstance(content, dict):
        return None
    operation = content.get("operation")
    if not isinstance(operation, str):
        return None
    evidence = content.get("evidence") if isinstance(content.get("evidence"), dict) else {}
    dispatched = evidence.get("dispatched")
    if not isinstance(dispatched, bool):
        # Older receipts predate the dispatch flag. A verified success was
        # necessarily dispatched; otherwise leave the question open.
        dispatched = True if content.get("status") == "success" else None
    status = content.get("status")
    outcome = _ACTION_OUTCOMES.get((status, dispatched))
    if outcome is None:
        outcome = "结果无法确认" if dispatched is None else "结果无法确认"
    record = {"来源": "动作执行回执", "动作": _ACTION_LABELS.get(operation, operation),
              "结果": outcome}
    target = evidence.get("path") or content.get("target")
    if isinstance(target, str) and target.strip():
        record["对象"] = _brief(target, 120)
    if isinstance(evidence.get("bytes"), int):
        record["写入字节"] = str(evidence["bytes"])
    if dispatched is False:
        reason = content.get("detail")
        if isinstance(reason, str) and reason.strip():
            record["未执行的原因"] = _brief(reason, 120)
    if isinstance(receipt.get("created_at"), str):
        record["时间"] = receipt["created_at"]
    record["说明"] = "这是执行器返回的记录，不是推测；不要否认已通过校验的操作，也不要把未执行说成完成。"
    return record


def _terms(text: str) -> list[str]:
    tokens = []
    for token in re.findall(r"[\w]+", text.casefold()):
        if re.search(r"[㐀-鿿]", token):
            tokens.extend(token[index:index + 2] for index in range(max(1, len(token) - 1)))
        elif len(token) >= 2:
            tokens.append(token)
    return list(dict.fromkeys(tokens))


def _overlap(claim_terms: list[str], candidate: str) -> float:
    if not claim_terms:
        return 0.0
    body = candidate.casefold()
    return sum(1 for term in claim_terms if term in body) / len(claim_terms)


def _claimed_content(text: str) -> str | None:
    quoted = _QUOTED.search(text)
    if quoted:
        return quoted[1].strip()
    after = _AFTER_VERB.search(text)
    if after and after[1].strip():
        return after[1].strip()
    return None


def premise_records(store, text: str, *, session_id: str, scope: str) -> list[dict[str, str]]:
    """Check an asserted earlier statement against the ledger before replying.

    Failure 4 — agreeing with a false correction premise — is not fixed by
    another prompt paragraph. The turn needs the answer to "did that actually
    happen" as evidence, so a correction can be accepted or declined on record.
    """
    if not _PRIOR_CLAIM.search(text):
        return []
    claim = _claimed_content(text)
    header = {"来源": "对本轮说法的记录核对",
              "核对范围": "本会话已完成的对话记录与当前有效的长期记忆"}
    if claim:
        header["对方引用的内容"] = _brief(claim, 120)
    terms = _terms(claim or text)
    best_score, best_role, best_text = 0.0, None, None
    for message in store.history(session_id, scope=scope, limit=60):
        score = _overlap(terms, message["content"])
        if score > best_score:
            best_score, best_role, best_text = score, message["role"], message["content"]
    for memory in store.memories(scope=scope):
        score = _overlap(terms, memory["statement"])
        if score > best_score:
            best_score, best_role, best_text = score, "memory", memory["statement"]
    if len(terms) < 3:
        # Too little to match on. Confirming here would be the same mistake as
        # agreeing with the premise outright, so it stays undecided.
        header["结果"] = "引用的内容太短，无法核对"
        header["说明"] = ("不要仅凭这句话确认或否认。可以请对方说得具体一点，"
                          "或说明需要更完整的原话才能查。")
    elif best_score >= 0.6 and best_text:
        header["结果"] = "记录中有相符的内容"
        header["记录中的原话"] = _brief(best_text, 200)
        header["说话者"] = {"user": "用户", "assistant": "栖音", "memory": "已保存的长期记忆"}[best_role]
        header["说明"] = "可以据此确认。仍要核对说话者：旧的自述只说明说过，不证明做过。"
    else:
        header["结果"] = "没有找到相符的内容"
        header["说明"] = ("记录不支持这句话。如实说明没有这条记录，请对方补充；"
                          "不要顺着确认，也不要据此补造经历或道歉式承认。"
                          "记录可能不完整，所以说的是没有记录，不是断定对方记错。")
    return [header]


def _memory_matches(store, scope, pattern):
    return [memory for memory in store.memories(scope=scope) if pattern.search(memory["statement"])]


def _event_matches(store, session_id, scope, pattern):
    found = []
    for event in store.list_events(session_id, scope):
        if (event["origin"] in {"generated", "reflection", "inference", "simulation", "design_seed"}
                or event["status"] in {"generated", "partial", "cancelled", "failed", "unknown"}):
            continue
        if event["kind"] in {"user", "user_turn", "assistant", "assistant_turn"} and pattern.search(event["content"]):
            found.append(event)
    return found


def topic_records(store, text: str, *, session_id: str, scope: str) -> list[dict[str, str]]:
    """State the real inventory for topics the report showed her inventing.

    Only the topics actually raised are projected, so the context budget is
    spent on the question being asked rather than on a standing disclaimer.
    """
    records: list[dict[str, str]] = []
    if _QINAI.search(text):
        memories = _memory_matches(store, scope, _QINAI)
        events = _event_matches(store, session_id, scope, _QINAI)
        record = {"来源": "记录清单", "主题": "与祈奈相关的记录",
                  "已保存的长期记忆": f"{len(memories)} 条",
                  "本会话对话记录": f"{len(events)} 条"}
        if memories:
            record["记忆内容"] = _brief("；".join(item["statement"] for item in memories), 200)
        record["说明"] = ("姐妹关系是身份约定，共同经历必须有记录。没有记录时说明还没有一起经历过什么，"
                          "不要描述没有发生的合作、对话或玩过的东西。")
        records.append(record)
    if _BACKGROUND.search(text):
        activity = [event for event in store.list_events(session_id, scope)
                    if event["kind"] in {"action_result", "body_observation", "sleep_summary"}
                    and event["status"] in {"verified_success", "verified_failure", "recorded", "completed"}]
        record = {"来源": "记录清单", "主题": "对话之外的活动",
                  "本会话记录到的活动": f"{len(activity)} 次"}
        if activity:
            record["最近一次"] = _brief(activity[-1]["kind"] + " @ " + activity[-1]["created_at"], 120)
        record["说明"] = ("没有记录的时间段不产生经历。不在运行或没有活动时如实说明，"
                          "不要描述后台思考、观察或练习。")
        records.append(record)
    if _PREFERENCE.search(text):
        stored = [memory for memory in store.memories(scope=scope)
                  if memory["kind"] in {"preference", "opinion"}]
        record = {"来源": "记录清单", "主题": "已保存的偏好与观点",
                  "条数": f"{len(stored)} 条"}
        if stored:
            record["内容"] = _brief("；".join(item["statement"] for item in stored), 240)
            record["说明"] = "这些是有依据的长期偏好，可以直接说。其它想法属于此刻的反应，说清楚是当下的感觉。"
        else:
            record["说明"] = ("还没有保存过偏好。可以说明还在形成，或说这是此刻的感觉；"
                              "不要临时编一个并说成一直以来的喜好。")
        records.append(record)
    return records


def json_size(records) -> int:
    return len(json.dumps(records, ensure_ascii=False, separators=(",", ":")))
