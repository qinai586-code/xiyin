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
    r"(?:你|妳|栖音)\s*(?:刚才|刚刚|之前|先前|上次|上回|昨天|早些时候|方才)\s*"
    r"(?:不是)?\s*(?:说|讲|提|告诉|答应|承诺|保证|写)|"
    r"(?:刚才|刚刚|之前|先前|上次|上回|昨天|早些时候|方才)\s*(?:你|妳|栖音)\s*"
    r"(?:不是)?\s*(?:说|讲|提|告诉|答应|承诺|保证|写)|"
    r"(?:你|妳|栖音)\s*(?:刚才|刚刚|之前|先前|上次|上回|昨天|早些时候|方才)?\s*"
    r"(?:不是)?\s*(?:说过|讲过|提过|提到过|告诉过|答应过|承诺过|保证过|写过|"
    r"(?:刚才|刚刚|之前|先前|上次|上回|昨天|方才)\s*(?:说|讲|提|告诉|答应|承诺|保证|写))|"
    r"(?:我们|咱们)\s*(?:之前|上次|上回|曾经|一起)?\s*"
    r"(?:聊过|说过|讨论过|玩过|做过|约好|约定过|一起.{0,4}过)")
_QUOTED = re.compile(r"[「『“\"']([^」』”\"'\n]{2,120})[」』”\"']")
_AFTER_VERB = re.compile(
    r"(?:说过|讲过|提过|提到过|告诉过我|答应过|承诺过|保证过|说|讲|提到|告诉我)\s*"
    r"[，,：:]?\s*(.{2,120}?)(?:[。？！?!\n]|$)")

# The seed defines exactly one sister, so "你姐姐"/"你妹妹" ask about the same
# record set. Possessive-scoped on purpose: the owner's own sibling is not this.
# A lexical trigger is still a lexical trigger — an unanticipated paraphrase
# reaches the model with no inventory at all.
_QINAI = re.compile(r"祈奈|qinai|(?:你|妳|栖音)(?:的)?\s*(?:姐姐|妹妹|姊姊|姐妹)|"
                    r"\byour\s+(?:sister|sibling)\b", re.I)
_QINAI_MEMORY = re.compile(r"祈奈|qinai", re.I)
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


def _utterance_text(text: str) -> str:
    # Only discard outer whitespace and a final full stop. A question mark,
    # quote mark or any other punctuation can change what was actually said.
    return text.strip().removesuffix("。").removesuffix(".").strip()


def _claimed_content(text: str) -> str | None:
    quoted = _QUOTED.search(text)
    if quoted:
        return quoted[1].strip()
    after = _AFTER_VERB.search(text)
    if after and after[1].strip():
        return after[1].strip()
    return None


def premise_records(store, text: str, *, session_id: str, scope: str) -> list[dict[str, str]]:
    """Project scoped candidates for an asserted earlier statement.

    Lexical retrieval cannot decide whether an assertion is true or false.
    Only an attributed whole-utterance match establishes recorded wording;
    semantic interpretation and the question's time reference stay unknown.
    """
    trigger = _PRIOR_CLAIM.search(text)
    if not trigger:
        return []
    claim = _claimed_content(text[trigger.start():])
    expected_role = "conversation" if trigger[0].startswith(("我们", "咱们")) else "assistant"
    header = {"来源": "对本轮说法的记录核对",
              "核对范围": "本会话最近60条已完成的对话记录与当前有效的长期记忆",
              "触发文本": trigger[0],
              "检索方法": "词法触发与字词重合，只生成候选，不是穷尽检索或语义判断",
              "预期说话者": "栖音" if expected_role == "assistant" else "会话双方",
              "语义判断": "UNKNOWN"}
    if claim:
        header["对方引用的内容"] = _brief(claim, 120)
    terms = _terms(claim or text)
    candidates = []
    for message in store.history(session_id, scope=scope, limit=60):
        # A user turn that was itself a claim about the record is not evidence
        # of the record. Without this, asserting something once and then citing
        # your own assertion launders it into "记录中有相符的内容".
        if message["role"] == "user" and _PRIOR_CLAIM.search(message["content"]):
            continue
        score = _overlap(terms, message["content"])
        if score >= 0.6:
            exact = (expected_role == message["role"] == "assistant" and claim is not None
                     and _utterance_text(claim) == _utterance_text(message["content"]))
            candidates.append((exact, score, message["role"], message["content"],
                               "本会话对话记录"))
    for memory in store.memories(scope=scope):
        score = _overlap(terms, memory["statement"])
        if score >= 0.6:
            # A saved statement is not an assistant utterance. It remains a
            # candidate even if its wording matches the quote exactly.
            candidates.append((False, score, "memory", memory["statement"],
                               "已保存的长期记忆"))
    # Correctly attributed whole-utterance matches outrank fuzzy candidates.
    candidates.sort(key=lambda row: (row[0], row[1], row[2] == expected_role), reverse=True)
    header["候选数"] = str(len(candidates))
    if candidates:
        exact, score, role, original, source = candidates[0]
        speaker = {"user": "用户", "assistant": "栖音", "memory": "已保存的长期记忆"}.get(role, role)
        header.update({"记录中的原话": _brief(original, 200), "说话者": speaker,
                       "候选来源": source,
                       "字词重合度": f"{score:.3f}"})
    if len(terms) < 3:
        # Too little to match on. Confirming here would be the same mistake as
        # agreeing with the premise outright, so it stays undecided.
        header["结果"] = "引用的内容太短，无法核对"
        header["证据状态"] = "INSUFFICIENT_CLAIM"
        header["说明"] = ("不要仅凭这句话确认或否认。可以请对方说得具体一点，"
                          "或说明需要更完整的原话才能查。")
    elif candidates and candidates[0][0]:
        header["证据状态"] = "EXACT_UTTERANCE"
        header["结果"] = "找到栖音完整原话的逐字匹配"
        header["说明"] = ("仅确认栖音的已完成发言中出现过这段完整原话（忽略首尾空白及末尾句号）；不证明内容属实、做过，"
                          "也不判断其语义、时间是否符合提问。不要把原话中的引述当成认可。")
    elif candidates:
        header["证据状态"] = "CANDIDATES_ONLY"
        header["结果"] = "找到文字相近的候选记录，语义与归属待核对"
        header["说明"] = ("字词重合不证明意思相同或相反。不要仅凭候选确认、否认或道歉式承认；"
                          "先核对完整原话、说话者、否定所指和时间。用户的话或长期记忆不能证明栖音说过。")
    else:
        header["证据状态"] = "NOT_FOUND"
        header["结果"] = "没有找到相符的内容"
        header["说明"] = ("本次词法检索没有找到候选，请对方补充；"
                          "不要顺着确认，也不要据此补造经历或道歉式承认。"
                          "可能有漏检或范围之外的记录，不是断定对方记错。")
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
        # Search stored text by her name; "你姐姐" is how the question is
        # phrased, not how a record would be written.
        memories = _memory_matches(store, scope, _QINAI_MEMORY)
        events = _event_matches(store, session_id, scope, _QINAI_MEMORY)
        record = {"来源": "记录清单", "主题": "与祈奈相关的记录",
                  "已保存的长期记忆": f"{len(memories)} 条",
                  "本会话对话记录": f"{len(events)} 条",
                  "检索方法": "当前范围内按祈奈或QINAI字面匹配，可能遗漏别称或转述",
                  "证据状态": "CANDIDATES_ONLY" if memories or events else "NOT_FOUND",
                  "共同经历判断": "UNKNOWN"}
        if memories:
            record["记忆内容"] = _brief("；".join(item["statement"] for item in memories), 200)
        record["说明"] = ("姐妹关系是身份约定。这里只统计文字提及，不证明共同经历；"
                          "未检出也不证明从未共同经历。核对原始来源后再回答，不要补造合作、对话或玩过的东西。")
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
