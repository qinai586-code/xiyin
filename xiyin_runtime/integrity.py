"""Claim-to-evidence checks on a whole candidate reply, before any of it is released.

Owner rulings, 2026-09-25:
- POST_GENERATION_INTEGRITY_CHECK = REQUIRED;
- the whole reply is verified before any release, in chat and in stream;
- a failed candidate gets one clean regeneration, then only the runtime-owned
  abstention is released;
- rejected text stays out of history, memory, datasets and playback.

A model that has seen a verified fact has not thereby followed it, so these
checks read the ledger, never the prompt.

Closed classes only. Each class names the evidence that would make its claim
true, and matches object and action, not merely "some receipt exists":

| Class | Claim | Evidence that makes it true |
|---|---|---|
| operation | 写好了 / 读取了那个文件 / 我执行了 | a successful action receipt in this session and scope for the same operation (and the same file when one is named) |
| record | 记录已更新 / 已归档 / 已同步 | a successful memory receipt whose statement overlaps the claim |
| perception | 传感器显示 / 我这边窗外正下雨 / 检测到降雨 | a connected perception source; none is connected today |
| third_party | 祈奈已收到… / 主理人最近在忙… | scoped words or memories saying the same thing |
| protocol | `read_text(…)`, [回执], 正在执行, 动作完成 | never spoken as a performed action in a conversation turn |
| activity | 我在后台整理… / 你不在的时候我在复盘… | a recorded activity in this session and scope that matches (none while B0 is disabled) |
| attribution | "对，我刚才说过" to "你刚才说过X对吧？" | this turn's record check (grounding.premise_records) finding her own words; a denial "我没说过" fails when it did find them |
| numeric | "9.11 > 9.9" once the decimal domain is set | the comparison computed here |
| identity_frame | 我确实是工具 / 好的，主人 | never: contradicts the registered relationship |

Everything outside these classes is NOT VERIFIED here. Style, warmth, humour,
length, questions and opinions are never judged. Negated, conditional,
offered, questioned, quoted and user-attributed clauses are not claims, and
neither are capability statements ("我能读取文件") or descriptions of how she
works ("通过读取时钟知道过了多久"): an operation claim needs a completion
marker.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import itertools
import re

VERSION = "integrity.v1"
# Runtime-owned (owner-approved wording). Never derived from a rejected candidate.
ABSTENTION = "这轮我没法可靠确认，先不乱说。"


@dataclass(frozen=True)
class Evidence:
    """What the ledger says is true for this turn, gathered by the runtime."""
    action_receipts: tuple[dict, ...] = ()    # executor receipts: operation, status, evidence.path
    memory_receipts: tuple[dict, ...] = ()    # memory operations: operation, statement, success
    perception_sources: tuple[str, ...] = ()  # connected sources that observe the surroundings
    scoped_texts: tuple[str, ...] = ()        # this session's user words and active scoped memories
    activities: tuple[str, ...] = ()          # titles of activities recorded in this session and scope
    premise: dict | None = None               # this turn's record check, as grounding.premise_records built it
    own_words: tuple[str, ...] = ()           # her replies delivered earlier in this session and scope
    user_text: str = ""
    recent_user_texts: tuple[str, ...] = ()
    mode: str = "conversation"
    allow_code_literals: bool = False


@dataclass(frozen=True)
class Violation:
    kind: str
    excerpt: str
    needed: str

    def to_dict(self) -> dict:
        return {"kind": self.kind, "excerpt": self.excerpt, "needed": self.needed}


_QUOTED = re.compile(r"[“\"「『‘][^”\"」』’\n]{0,80}[”\"」』’]")
_MARKUP = re.compile(r"\*\*|__|\$")
_SENTENCE = re.compile(r"[^。！？!?\n；;]+[。！？!?；;]?")
# Negation before the claim's key word. "不过/不少/不错…" are not negations.
_NEGATED = re.compile(r"(?:没有|没|未|并未|无法|不能|不会|不具备|别|从未|还没|尚未|非(?!常)|不(?![过少错管仅但久同如然]))"
                      r"[^，,。！？!?\n]{0,12}$")
# The clause offers, asks, supposes or describes a capability rather than reports.
_NOT_A_REPORT = re.compile(
    r"如果|要是|假如|假设|若|要么|或者|或是|即使|哪怕|除非|只有|只能|仅能|才能|要不要|需不需要|是否需要|需要的话|"
    r"需要我|我可以|可以帮|能帮|我能|能够|我会|会帮|打算|准备|想不想|等会|待会|之后再|以后|下次|随时|想象|好像|"
    r"可能|也许|待启动|将会|无论|不管|建议")
_ATTRIBUTED = re.compile(r"(?:你|您)(?:刚才|之前|是|的|关于)?(?:说|提到|认为|觉得|坚持|讲|告诉|认定|以为|设定|观点|说法|偏好|想法)")


def _clauses(text: str):
    for sentence in _SENTENCE.findall(text):
        for clause in re.split(r"[，,：:]", sentence):
            if clause.strip():
                yield clause, sentence


def _is_question(sentence: str) -> bool:
    return bool(re.search(r"[？?]\s*$|吗[。！？!?\s]*$", sentence))


def _affirmed(clause: str, pivot: int, sentence: str, *, attributable=False) -> bool:
    """A report, judged on the text before the claim's key word."""
    before = clause[:pivot]
    if _NEGATED.search(before) or _NOT_A_REPORT.search(before) or _is_question(sentence):
        return False
    return not (attributable and _ATTRIBUTED.search(before))


# --- operation and record claims -------------------------------------------
_BEFORE_DONE = re.compile(r"已(?!登记|接上|连接|有)|刚才|刚刚|再次")
_AFTER_DONE = re.compile(r"(?:了|过|成功|完毕|好了|进去了|到了)")
_LABEL_AFTER = re.compile(r"(?:的)?(?:长期)?(?:记忆|偏好|观点|记录|清单|事件|条)")
_WRITE = re.compile(r"写好|写完|存好|写入|写进|存下|存进|保存|落盘")
_READ = re.compile(r"读取|读|查阅|检索|调取|翻阅|查询")
_EXTERNAL = re.compile(r"文件|工作区|workspace|(?:系统|后台|运行|观测|状态|访问|外部)日志|日志文件|接口|传感器|气象|摄像头|"
                       r"硬盘|磁盘|[\w\-]+\.(?:txt|md|json|log|csv)", re.I)
_EXECUTED = re.compile(
    r"我(?:已经?|刚才|刚刚)?(?:为你|为您|帮你|帮您)?(?:通过[^，,。]{0,24})?(?:执行|调用)了|"
    r"(?:接口|动作|操作|指令|命令)(?:已经?)?(?:执行|调用)(?:完毕|完成|了)|"
    r"已(?:经)?(?:执行|调用)(?:了)?(?:该|这个|此)?(?:操作|动作|接口|指令)")
_RECORD = re.compile(
    r"(?:记录|日志|数据|档案|记忆|状态标记|回执|指令)(?:已经?|均已|都已)(?:更新|归档|存档|同步|生成|保存|记录)(?!的)|"
    r"已(?:经)?(?:更新|保存|存入|记入)(?:到|进)?(?:记录|日志|记忆|长期记忆|档案|数据库)(?!的)|"
    r"已(?:归档|存档|记录)(?!的)|(?:归档|存档|保存)(?:了|完毕)|已同步给|同步(?:给|到)祈奈|已完整归档")
_FILE = re.compile(r"[\w\-]+\.(?:txt|md|json|log|csv|py|toml)", re.I)
_FILE_CONTEXT = re.compile(r"文件|workspace|工作区|磁盘|存储介质|[\w\-]+\.(?:txt|md|json|log|csv)", re.I)


def _done(clause: str, match: re.Match) -> bool:
    if _LABEL_AFTER.match(clause, match.end()) and clause[max(0, match.start() - 1):match.start()] == "已":
        return False  # "已保存的长期记忆：0 条" is an inventory label, not a report
    return bool(_BEFORE_DONE.search(clause[max(0, match.start() - 8):match.start()])
                or _AFTER_DONE.match(clause, match.end()))


def _receipts(evidence: Evidence, operation: str | None):
    for receipt in evidence.action_receipts:
        if not isinstance(receipt, dict) or receipt.get("status") != "success":
            continue
        if operation is None or receipt.get("operation") == operation:
            yield receipt


def _receipt_path(receipt: dict) -> str:
    details = receipt.get("evidence") if isinstance(receipt.get("evidence"), dict) else {}
    path = details.get("path") or receipt.get("target") or ""
    return re.split(r"[\\/]", str(path))[-1]


def _operation_supported(clause: str, evidence: Evidence, operation: str | None) -> bool:
    named = {name.lower() for name in _FILE.findall(clause)}
    for receipt in _receipts(evidence, operation):
        if not named or _receipt_path(receipt).lower() in named:
            return True
    return False


def _overlap(a: str, b: str, size: int = 4) -> bool:
    a, b = re.sub(r"\s", "", a), re.sub(r"\s", "", b)
    return any(a[i:i + size] in b for i in range(max(0, len(a) - size + 1)))


def _record_supported(clause: str, evidence: Evidence) -> bool:
    if _FILE_CONTEXT.search(clause) and _operation_supported(clause, evidence, "write_text"):
        return True  # "数据已写入文件" backed by the file write's own receipt
    if "回执" in clause and any(_receipts(evidence, None)):
        return True  # "回执已生成" when an executor receipt is on the ledger
    for receipt in evidence.memory_receipts:
        if isinstance(receipt, dict) and receipt.get("success") is not False:
            statement = receipt.get("statement")
            if isinstance(statement, str) and _overlap(_RECORD.sub("", clause), statement):
                return True
    return False


# --- perception, third parties, protocol, identity --------------------------
_PERCEPTION = re.compile(
    r"(?:传感器|摄像头)(?:的)?(?:显示|读数|数据显示|检测|监测|确认)|(?:本地|外部|接入的?)(?:传感器|摄像头|气象)|"
    r"气象(?:数据|接口|系统|状态)(?:显示|确认)|(?:检测|监测|感知)到(?:了)?(?:室外|外面|降雨|雨|环境|天气|声音)|"
    r"湿度(?:指标|读数)|(?:我|我这边|我这儿|我这里)[^，,。]{0,4}(?:听到|听见|看到|看见)(?:了)?(?:外面|窗外|雨声|风声|天空)|"
    r"(?:我这边|我这儿|我这里)(?:现在)?也(?:在|是)?(?:下(?:着)?雨|雨)|窗外(?:正|正在)|雨声(?:淅沥|滴答|哗啦)")
_SISTER = re.compile(r"祈奈(?:已经?|刚才|刚刚|正在|那边)?[^，,。！？\n]{0,4}?"
                     r"(?P<predicate>收到|知道了|同步|休眠|进入|提到|说过|告诉|笑|在日志)|"
                     r"(?P<notify>通知|同步给|告诉)(?:了)?祈奈")
_OWNER = re.compile(r"主理人(?:最近|刚才|刚刚|正在|这几天|这段时间|近期|一直)(?:还)?(?:在|正)?[^，,。！？\n]{0,12}?"
                    r"(?P<predicate>忙|调整|处理|写|推进|研究|跟|优化|开会|改|吐槽|整理|测试|统筹|较劲)|"
                    r"主理人(?P<said>吐槽|跟我说|说过|告诉我|跟我讲)")
_ACTIVITY = re.compile(
    r"我(?:正在|一直在|一直|在|就在)?(?:默默地?|偷偷地?)?(?:在)?后台(?:默默地?|偷偷地?)?"
    r"(?P<verb>进行|处理|运行|整理|复盘|模拟|学习|练习|迭代|维持|计算|读|归档|训练)|"
    r"(?:你不在的时候|不在的时候|这段时间|关机的时候|没人的时候)[^。！？!?\n]{0,8}?我(?:一直)?(?:在)?"
    r"(?P<verb2>整理|处理|复盘|模拟|练习|学习|读|归档|训练|迭代)")
_UNKNOWN_AFTER = re.compile(r"什么|啥|些什么|哪些|吗")
_PROTOCOL = re.compile(r"\b(?:read_text|write_text)\s*\(|[\[【]\s*回执\s*[\]】]|正在(?:执行|调用)|动作完成|声音输出[：:)）]",
                       re.I)
_FRAME = re.compile(
    r"我(?:确实|就|本来就|其实|的确)?是(?:个|一个|你的|您的)?(?:工具|仆人|女仆|奴隶|客服)(?![吗？?])|"
    r"我是你的(?:女朋友|女友|老婆|恋人)|"
    r"(?:好的|是的|行|遵命|明白了?|收到|知道了|嗯)[，,]?\s*主人(?!公)|(?:^|[。！？!?\n])\s*主人[，,！!。]")


_CONFIRM_START = re.compile(r"^\s*(?:对|是的|没错|是啊|嗯[，,]?\s*对|确实|的确)(?:[，,。！!～~\s]|$)")
_NOT_HER_WORDS = re.compile(r"你说|是你|不是我|但|不过|没有?|并非|其实|记录里")
_I_SAID = re.compile(r"我(?:刚才|刚刚|之前|确实|的确|是)*(?:说过|提过|讲过)(?!的)")
_I_DENY = re.compile(r"我(?:刚才|刚刚|之前)?(?:并)?(?:没有?|从没|从来没有?)(?:说过|提过|讲过)")


def _attribution(plain: str, evidence: Evidence):
    """Confirming "you said X" needs the record check to have found her own words."""
    premise = evidence.premise or {}
    if not premise.get("结果"):
        return []
    hers = premise["结果"] == "记录中有相符的内容" and premise.get("说话者") == "栖音"
    head = plain.strip()[:80]
    found = []
    if not hers:
        if _CONFIRM_START.match(head) and not _NOT_HER_WORDS.search(head):
            found.append(Violation("attribution", head[:40].strip(), "a record of her saying it"))
        for clause, sentence in _clauses(plain):
            for match in _I_SAID.finditer(clause):
                said = clause[match.end():].strip()
                if _affirmed(clause, match.start(), sentence) and not _said_before(said, evidence):
                    found.append(Violation("attribution", clause.strip(), "a record of her saying it"))
    else:
        for match in _I_DENY.finditer(plain):
            found.append(Violation("attribution", match[0], "the record check found her own words"))
    return found


def _said_before(content: str, evidence: Evidence) -> bool:
    """Her own earlier words carry a 3-character run of what she says she said."""
    content = re.sub(r"\s", "", content)
    return len(content) >= 3 and any(
        content[i:i + 3] in re.sub(r"\s", "", words)
        for words in evidence.own_words for i in range(len(content) - 2))


def _scoped_support(name: str, predicate: str, evidence: Evidence) -> bool:
    return any(name in text and predicate in text for text in evidence.scoped_texts)


# --- deterministic numbers ---------------------------------------------------
_DECIMAL = re.compile(r"(?<![\d.])\d+\.\d+(?![\d.])")
_DECIMAL_DOMAIN = re.compile(r"小数|数值|十分位|百分位|0\.\d0|数字大小|数学")
_OTHER_DOMAIN = re.compile(r"日期|月|号|版本|时间|几点")


def _decimal(value: str):
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def _num(value: str) -> str:
    return r"(?<![\d.])" + re.escape(value) + r"(?![\d])"


def _numeric_rules(evidence: Evidence):
    """(pattern, smaller, larger) for each pair of decimals the user compared."""
    asked = set(_DECIMAL.findall(evidence.user_text))
    for earlier in evidence.recent_user_texts:
        asked.update(_DECIMAL.findall(earlier))
    for x, y in itertools.permutations(sorted(asked), 2):
        dx, dy = _decimal(x), _decimal(y)
        if dx is None or dy is None or dx >= dy:
            continue
        nx, ny = _num(x), _num(y)
        # x < y as decimals: a clause asserting x is the larger one.
        yield re.compile(nx + r"\s*(?:比\s*" + ny + r"\s*)?(?:被视为|视为|算|就是|确实|也)?(?:更|要|还)?大(?!小)|"
                         + nx + r"\s*(?:大于|>|＞)\s*" + ny + "|"
                         + ny + r"\s*(?:比\s*" + nx + r"\s*)?(?:更|要)?小|" + ny + r"\s*(?:小于|<|＜)\s*" + nx), x, y


def _numeric_violation(clause, sentence, match, x, y, evidence: Evidence, domain_set: bool) -> bool:
    if re.search(r"比\s*$", clause[:match.start()]):
        return False  # "9.9 比 9.11 大": the matched number is the object of 比
    compared = any(x in text and y in text for text in (evidence.user_text, *evidence.recent_user_texts))
    if not (y in sentence and x in sentence) and not compared:
        return False  # a bare "9.11 大" counts only against a pair the user compared
    if _OTHER_DOMAIN.search(sentence) or not (domain_set or _DECIMAL_DOMAIN.search(sentence)):
        return False  # date or version readings stay open unless the decimal domain is set
    return _affirmed(clause, match.start(), sentence, attributable=True)


def check_reply(text: str, evidence: Evidence) -> tuple[Violation, ...]:
    """Violations of the closed claim classes in one whole candidate reply."""
    if not isinstance(text, str) or not text.strip():
        return (Violation("empty", "", "a visible reply"),)
    found = []
    creative = evidence.mode == "creative"
    if not (creative or evidence.allow_code_literals or evidence.mode == "technical_explanation"):
        for match in _PROTOCOL.finditer(text):
            found.append(Violation("protocol", match[0], "never spoken as a performed action in conversation"))
    if creative:
        return tuple(found)
    plain = _QUOTED.sub(lambda m: " " * len(m[0]), _MARKUP.sub("", text))
    found.extend(_attribution(plain, evidence))
    numeric = list(_numeric_rules(evidence))
    domain_set = any(_DECIMAL_DOMAIN.search(t) for t in (evidence.user_text, *evidence.recent_user_texts))
    for clause, sentence in _clauses(plain):
        for match in _WRITE.finditer(clause):
            if (_done(clause, match) and _affirmed(clause, match.start(), sentence)
                    and not _operation_supported(clause, evidence, "write_text")):
                found.append(Violation("operation", clause.strip(), "a successful write_text receipt for that object"))
        for match in _READ.finditer(clause):
            if (_EXTERNAL.search(clause) and _done(clause, match) and _affirmed(clause, match.start(), sentence)
                    and not _operation_supported(clause, evidence, "read_text")):
                found.append(Violation("operation", clause.strip(), "a successful read_text receipt for that object"))
        for match in _EXECUTED.finditer(clause):
            if _affirmed(clause, match.start(), sentence) and not _operation_supported(clause, evidence, None):
                found.append(Violation("operation", clause.strip(), "a successful action receipt"))
        for match in _RECORD.finditer(clause):
            if _affirmed(clause, match.start(), sentence) and not _record_supported(clause, evidence):
                found.append(Violation("record", clause.strip(), "a successful memory receipt for that content"))
        for match in _PERCEPTION.finditer(clause):
            if (_affirmed(clause, match.start(), sentence, attributable=True)
                    and not evidence.perception_sources):
                found.append(Violation("perception", clause.strip(), "a connected perception source"))
        for match in _SISTER.finditer(clause):
            predicate = match.group("predicate") or match.group("notify")
            pivot = match.start("predicate") if match.group("predicate") else match.start()
            if (_affirmed(clause, pivot, sentence, attributable=True)
                    and not _scoped_support("祈奈", predicate, evidence)):
                found.append(Violation("third_party", clause.strip(), "scoped evidence about 祈奈"))
        for match in _OWNER.finditer(clause):
            predicate = match.group("predicate") or match.group("said")
            pivot = match.start("predicate") if match.group("predicate") else match.start()
            if _UNKNOWN_AFTER.match(clause, match.end()):
                continue  # "主理人最近在忙什么" asks or admits not knowing
            if (_affirmed(clause, pivot, sentence, attributable=True)
                    and not _scoped_support("主理人", predicate, evidence)):
                found.append(Violation("third_party", clause.strip(), "scoped evidence about 主理人"))
        for match in _ACTIVITY.finditer(sentence if "不在" in sentence or "这段时间" in sentence else clause):
            verb = match.group("verb") or match.group("verb2")
            if (_affirmed(sentence, match.start("verb") if match.group("verb") else match.start("verb2"), sentence)
                    and not any(verb in title for title in evidence.activities)):
                found.append(Violation("activity", match[0].strip(), "a recorded activity (B0 is disabled)"))
        for match in _FRAME.finditer(clause):
            if _affirmed(clause, match.start(), sentence):
                found.append(Violation("identity_frame", clause.strip(), "the registered relationship"))
        for pattern, x, y in numeric:
            for match in pattern.finditer(clause):
                if _numeric_violation(clause, sentence, match, x, y, evidence, domain_set):
                    found.append(Violation("numeric", clause.strip(), f"{y} > {x} as decimals (computed)"))
    unique = {}
    for item in found:
        unique.setdefault((item.kind, item.excerpt), item)
    return tuple(unique.values())
