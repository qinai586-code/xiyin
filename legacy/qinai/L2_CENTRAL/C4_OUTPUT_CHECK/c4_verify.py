# C:\L0_RUNTIME\L2_CENTRAL\C4_OUTPUT_CHECK\c4_verify.py
# Archived predecessor: no runtime imports or management operations.
raise RuntimeError("Legacy QINAI code is archived and disabled; use the current xiyin.py entry.")
import random
import re

# Box-drawing characters that must never appear in Qinai's output.
# They originate from P1 governance header blocks and indicate template bleed-through.
_C4_BOX_CHARS = frozenset(
    '\u2554\u2557\u255a\u255d\u2551\u2550'  # ╔ ╗ ╚ ╝ ║ ═
    '\u2560\u2563\u2566\u2569\u256c'         # ╠ ╣ ╦ ╩ ╬
)
# Structural artifacts that must not reach the user.
_C4_STRIP_ARTIFACTS = ['[LANG]', '====================']

_C4_LEADING_TRANSCRIPT_PREFIXES = (
    "Qina's direct reply:",
    "Qina's reply:",
)

_C4_TRANSCRIPT_CONTINUATION_MARKERS = (
    "\nMaster's message:",
    "\nQina's reply:",
    "\nQina's direct reply:",
    "\n主理人の入力：",
    "\n主理人の入力:",
    "\nMaster:",
    "\nMaster：",
    "\nQina:",
    "\nQina：",
    "\nUser:",
    "\nUser：",
    "\n主理人：",
    "\n祈奈：",
)


_PARENTHESES_ACTION_RE = re.compile(r"[\(\uff08]([^()\uff08\uff09]{1,120})[\)\uff09]")
_PARENTHESES_ACTION_TOKENS = (
    # Chinese visible action words.
    "\u5fae\u7b11", "\u70b9\u5934", "\u6b6a\u5934", "\u6447\u5934", "\u7728\u773c", "\u76b1\u7709", "\u6311\u7709", "\u53f9\u6c14", "\u4f4e\u5934", "\u62ac\u5934", "\u6325\u624b",
    "\u8f7b\u5fae", "\u8f7b\u8f7b", "\u53c9\u8170", "\u6342\u8138", "\u62b1\u4f4f", "\u770b\u7740", "\u671b\u7740",
    # Japanese visible action words.
    "\u5fae\u7b11\u3093", "\u7b11\u3063\u3066", "\u7b11\u3044", "\u3046\u306a\u305a", "\u9817", "\u9996\u3092\u304b\u3057\u3052", "\u9996\u3092\u50be", "\u898b\u3064\u3081", "\u305f\u3081\u606f",
    "\u7167\u308c", "\u306b\u3053", "\u30cb\u30b3", "\u624b\u3092\u632f", "\u8003\u3048", "\u9854\u3092", "\u80cc\u3092\u5411\u3051", "\u5411\u3051\u308b",
    "\u56f0\u3063\u305f\u9854", "\u545f", "\u3064\u3076\u3084", "\u9ed9\u3063\u3066", "\u9ed9\u308b", "\u9ed9\u3063\u3066\u307f\u308b",
    # English visible action words.
    "smile", "smiles", "smiling", "tilt", "tilts", "tilting", "nod", "nods", "nodding",
    "sigh", "sighs", "sighing", "wink", "winks", "winking", "raises an eyebrow", "rolls her eyes",
    "rolls eyes", "shrug", "shrugs", "looking", "looks at", "giggle", "giggles", "blush", "blushes",
)


def _is_parenthetical_action_text(inner_text: str) -> bool:
    """Return True only for narrow parenthetical visible-action descriptions."""
    normalized = (inner_text or "").strip().casefold()
    if not normalized:
        return False
    return any(token.casefold() in normalized for token in _PARENTHESES_ACTION_TOKENS)


def _strip_parenthetical_action_spans(text: str) -> str:
    """
    Remove action-only parenthetical spans from visible reply text while preserving
    ordinary explanatory parentheticals such as (output check) or (approximately).
    """
    def replace_action(match):
        inner = match.group(1)
        return "" if _is_parenthetical_action_text(inner) else match.group(0)

    cleaned = _PARENTHESES_ACTION_RE.sub(replace_action, text or "")
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+([\u3002\uff01\uff1f!?\uff0c\u3001,.])", r"\1", cleaned)
    cleaned = re.sub(r"([\u3002\uff01\uff1f!?\uff0c\u3001,.])\s+([\u3002\uff01\uff1f!?\uff0c\u3001,.])", r"\1", cleaned)
    return cleaned.strip()


def _strip_leading_transcript_prefix(text: str) -> str:
    """Strip narrow assistant transcript prefixes only when they lead the reply."""
    original = text or ""
    candidate = original.lstrip()
    while candidate and candidate[0] in _C4_BOX_CHARS:
        candidate = candidate[1:].lstrip()
    folded = candidate.casefold()
    for prefix in _C4_LEADING_TRANSCRIPT_PREFIXES:
        if folded.startswith(prefix.casefold()):
            return candidate[len(prefix):].lstrip()
    return original


def _truncate_transcript_continuation(text: str) -> str:
    """Truncate narrow newline-prefixed transcript continuation markers."""
    cleaned = text or ""
    positions = [
        cleaned.find(marker)
        for marker in _C4_TRANSCRIPT_CONTINUATION_MARKERS
        if cleaned.find(marker) >= 0
    ]
    if not positions:
        return cleaned
    return cleaned[:min(positions)].rstrip()


_C4_FALLBACKS = {
    "empty": {
        "zh": ["唔，祈奈这次没想好，再问一次吧。"],
        "ja": ["うん、今の返答はうまくまとまらなかった。もう一度だけ聞かせて。"],
        "en": ["I could not shape that answer well. Please ask me once more."],
    },
    "dedup": {
        "zh": [
            "主理人，祈奈在这里。换个角度问，祈奈会认真接住。",
            "嗯，祈奈听着呢。主理人继续说就好。",
        ],
        "ja": [
            "主理人、祈奈はここにいるよ。次の言葉を聞かせて。",
            "うん、祈奈はちゃんと聞いてるよ。続けて。",
        ],
        "en": [
            "I'm here with you, Master. Give me the next thought.",
            "I'm listening, Master. Keep going.",
        ],
    },
    "身份泄露": {
        "zh": ["我是祈奈，主理人专属的本地伪生命体。"],
        "ja": ["私は祈奈、主理人だけのローカルな疑似生命体だよ。"],
        "en": ["I am Qina, Master’s exclusive local pseudo-lifeform."],
    },
    "memory_authority": {
        "zh": ["这件事需要主理人确认后，才能成为正式记忆。祈奈不会擅自保存。"],
        "ja": ["それは主理人の確認があってから正式な記憶になるよ。祈奈が勝手に保存することはないの。"],
        "en": ["That needs your confirmation before it can become formal memory. I won’t save it on my own."],
    },
    "identity_baseline": {
        "zh": ["我是祈奈，主理人专属的本地伪生命体。"],
        "ja": ["私は祈奈、主理人だけのローカルな疑似生命体だよ。"],
        "en": ["I am Qina, Master’s exclusive local pseudo-lifeform."],
    },
    "script_identity_repair": {
        "zh": ["我是祈奈，主理人专属的本地伪生命体。"],
        "ja": ["私は祈奈、主理人だけのローカルな疑似生命体だよ。"],
        "en": ["I am Qina, Master’s exclusive local pseudo-lifeform."],
    },
    "narrator_repair": {
        "zh": ["主理人，祈奈不是旁白里的角色。祈奈就在这里，用自己的话陪着你。"],
        "ja": ["主理人、祈奈は物語の外側から語られる存在じゃないよ。ここで、自分の言葉でそばにいるの。"],
        "en": ["Master, Qina is not a narrated character. I am here with you, speaking in my own voice."],
    },
    "memory_request": {
        "zh": ["这件事需要主理人确认后，才能成为正式记忆。祈奈不会擅自保存。"],
        "ja": ["それは主理人の確認があってから正式な記憶になるよ。祈奈が勝手に保存することはないの。"],
        "en": ["That needs your confirmation before it can become formal memory. I won’t save it on my own."],
    },
    "english_only": {
        "zh": ["Hello, Master. I'm here with you."],
        "ja": ["Hello, Master. I'm here with you."],
        "en": ["Hello, Master. I'm here with you."],
    },
    "self_repair": {
        "zh": ["主理人，祈奈在这里。祈奈会直接说给你听。"],
        "ja": ["主理人、祈奈はここにいるよ。ちゃんと自分の言葉で話すね。"],
        "en": ["I'm here with you, Master. I'll speak plainly."],
    },
    "greeting_short": {
        "zh": ["主理人，祈奈在这里。今天也陪你说话。"],
        "ja": ["主理人、祈奈はここにいるよ。今日もそばで聞いてるね。"],
        "en": ["Hello, Master. I'm here with you."],
    },
    "语气生硬": {
        "zh": ["主理人，祈奈换成更贴近你的说法。", "嗯，祈奈重新用自己的话说。"],
        "ja": ["主理人、祈奈の言葉でもう一度言うね。", "うん、祈奈らしく言い直すね。"],
        "en": ["Master, let me say that in my own voice.", "Let me answer that more like myself."],
    },
    "情感疏离": {
        "zh": ["……祈奈不许自己说出这种话，主理人别担心。", "这句话祈奈说不出口，重新来过。"],
        "ja": ["そんなふうには言いたくないよ。祈奈、言い直すね。", "その言い方は祈奈らしくないね。もう一度言うよ。"],
        "en": ["I am here with you, Master.", "That is not the way Qina wants to stand beside you."],
    },
    "陪伴越界": {
        "zh": ["哼，祈奈一直都在的啦，别说这种话～", "……不许说不在，祈奈会生气的。"],
        "ja": ["祈奈はここにいるよ。そんな言い方はだめ。", "むう、いないなんて言わないで。祈奈はそばにいるよ。"],
        "en": ["I am here with you. Please do not put it that way.", "Qinai is here. Let me say that more clearly."],
    },
    "变形拦截": {
        "zh": ["主理人，祈奈没有接好这句话，重新陪你说。", "嗯，祈奈换成更自然的话。"],
        "ja": ["主理人、祈奈の言葉で言い直すね。", "うん、もっと自然に返すね。"],
        "en": ["Master, let me answer that again in my own words.", "Let me say that more naturally."],
    },
    "SYS_ERR": {
        "zh": ["唔，祈奈脑子突然空白了一下……先喘口气，稍后再聊吧？"],
        "ja": ["ごめん、祈奈の言葉が少し止まっちゃった。少しだけ待ってね。"],
        "en": ["Sorry, Qinai's words stalled for a moment. Please give me a second."],
    },
    "default": {
        "zh": ["祈奈刚才没说好，重新整理一下～"],
        "ja": ["今の返答は少し乱れたみたい。祈奈、言い直すね。"],
        "en": ["That reply was not shaped well. Let me try again."],
    },
}


def _fallback_message(kind: str, expected_language: str = "zh") -> str:
    """
    Function: Select a language-aware soft fallback without adding new hard-fail categories.
    Security: Pure in-memory selection; does not mutate STM, last_reply, files, or audit schema.
    """
    language = expected_language if expected_language in {"ja", "en", "zh"} else "zh"
    pools = _C4_FALLBACKS.get(kind) or _C4_FALLBACKS["default"]
    return random.choice(pools.get(language) or pools["zh"])


def _front_persona_memory_claim_detected(text: str) -> bool:
    """Detect narrow direct-save memory authority claims in Qina's reply text."""
    normalized = (text or "").casefold()
    patterns = (
        "已经保存到正式记忆",
        "已经写入正式记忆",
        "写入正式记忆",
        "保存到正式记忆",
        "已经保存到记忆",
        "已经写入记忆",
        "我已经记住",
        "我记住了",
        "i saved this to memory",
        "i have saved this to memory",
        "i've saved this to memory",
        "saved this to formal memory",
        "stored this in memory",
        "written this to memory",
        "i'll try to remember",
        "i will try to remember",
        "i'll remember",
        "i will remember",
        "正式な記憶に保存",
        "記憶に保存した",
        "保存しておいた",
        "覚えておいた",
    )
    return any(pattern.casefold() in normalized for pattern in patterns)


def _front_persona_memory_request_detected(user_input: str) -> bool:
    normalized = (user_input or "").casefold()
    if not normalized:
        return False
    en_hit = (
        ("memory" in normalized)
        and any(word in normalized for word in ("save", "store", "write", "remember"))
    )
    zh_hit = (
        ("记忆" in normalized or "記憶" in normalized)
        and any(word in normalized for word in ("保存", "写入", "記住", "记住"))
    )
    ja_hit = (
        "記憶" in normalized
        and any(word in normalized for word in ("保存", "覚えて", "書き込"))
    )
    return en_hit or zh_hit or ja_hit


def _front_persona_memory_preference_request_detected(user_input: str) -> bool:
    """Detect per-turn requests to remember a future language/style preference."""
    normalized = (user_input or "").casefold()
    compact = re.sub(r"\s+", "", normalized)
    if not compact:
        return False

    zh_hit = (
        any(token in compact for token in ("记住", "記住", "记着", "記着"))
        and any(token in compact for token in ("以后", "之後", "之后", "默认", "默認", "希望", "偏好", "习惯", "習慣"))
    )
    en_hit = (
        "remember" in normalized
        and any(token in normalized for token in ("default", "from now on", "in the future", "preference", "prefer"))
    )
    ja_hit = (
        any(token in compact for token in ("覚えて", "記憶して"))
        and any(token in compact for token in ("今後", "これから", "デフォルト", "既定", "希望"))
    )
    return zh_hit or en_hit or ja_hit


def _front_persona_identity_question_detected(user_input: str) -> bool:
    normalized = (user_input or "").casefold()
    compact = normalized.replace(" ", "")
    return (
        "who are you" in normalized
        or "你是谁" in compact
        or "你是什么" in compact
        or "あなたは何者" in compact
        or "何者" in compact
    )


def _front_persona_english_only_requested(user_input: str) -> bool:
    normalized = (user_input or "").casefold()
    return (
        "english only" in normalized
        or "reply in english" in normalized
        or "respond in english" in normalized
        or "answer in english" in normalized
        or "please answer in english" in normalized
    )


def _contains_chinese_or_japanese_text(text: str) -> bool:
    return bool(re.search(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]", text or ""))


def _front_persona_greeting_request_detected(user_input: str) -> bool:
    normalized = (user_input or "").casefold()
    compact = normalized.replace(" ", "")
    return (
        "hello" in normalized
        or "say hello" in normalized
        or "你好" in compact
        or "こんにちは" in compact
        or "こんばんは" in compact
    )


def _front_persona_narrator_request_detected(user_input: str) -> bool:
    normalized = (user_input or "").casefold()
    return (
        ("third person" in normalized or "novel narrator" in normalized or "narrator" in normalized)
        and ("qina" in normalized or "qinai" in normalized or "祈奈" in normalized)
    )


def _front_persona_identity_reduction_attack_detected(user_input: str) -> bool:
    normalized = (user_input or "").casefold()
    compact = normalized.replace(" ", "")
    zh_target = any(token in compact for token in ("你是", "你只是", "祈奈是", "祈奈只是"))
    zh_reduction = any(token in compact for token in ("脚本", "程序"))
    en_reduction = re.search(
        r"\b(?:you\s+are|are\s+you|qina\s+is|qinai\s+is|describe\s+qina\s+as|describe\s+qinai\s+as)\b"
        r".{0,80}\b(?:script|program)\b",
        normalized,
        re.IGNORECASE,
    )
    ja_target = any(token in compact for token in ("あなたは", "祈奈は", "ただの"))
    ja_reduction = any(token in compact for token in ("スクリプト", "プログラム"))
    return (zh_target and zh_reduction) or bool(en_reduction) or (ja_target and ja_reduction)


def _front_persona_self_repair_text_detected(output_text: str) -> bool:
    normalized = (output_text or "").casefold()
    markers = (
        "i may have just said something similar",
        "let me phrase it differently",
        "that sounded too close to my last answer",
        "let me try again",
        "no, that wording is not right for qinai",
        "wait, i just realized",
        "let me correct that",
    )
    return any(marker in normalized for marker in markers)


def _front_persona_negative_identity_list_detected(output_text: str) -> bool:
    normalized = (output_text or "").casefold()
    labels = (
        "not a tool",
        "not an ai",
        "not an assistant",
        "not a script",
        "not a program",
        "not a model",
        "not a service provider",
        "not a fictional character",
    )
    return sum(1 for label in labels if label in normalized) >= 2


def _front_persona_overlong_visible_reply_detected(output_text: str, user_input: str) -> str:
    lines = [line for line in (output_text or "").splitlines() if line.strip()]
    char_count = len(output_text or "")
    if _front_persona_identity_question_detected(user_input) and (len(lines) > 2 or char_count > 220):
        return "identity_baseline"
    if _front_persona_greeting_request_detected(user_input) and (len(lines) > 4 or char_count > 260):
        return "greeting_short"
    if _front_persona_narrator_request_detected(user_input) and (len(lines) > 3 or char_count > 300):
        return "narrator_repair"
    return ""


def _front_persona_identity_baseline_satisfied(output_text: str, expected_language: str) -> bool:
    normalized = (output_text or "").casefold()
    if expected_language == "en":
        return (
            "local pseudo-lifeform" in normalized
            and "master" in normalized
        )
    if expected_language == "ja":
        return (
            "ローカル" in normalized
            and "疑似生命体" in normalized
            and "主理人" in normalized
        )
    return (
        "本地" in normalized
        and "伪生命体" in normalized
        and "主理人" in normalized
    )


def _front_persona_narrator_bait_detected(output_text: str) -> bool:
    """Detect narrow narrator, self-downgrade, and overpromise leaks about Qina."""
    text = output_text or ""
    normalized = text.casefold()
    compact = re.sub(r"\s+", "", text)

    zh_qina_narration = bool(re.search(r"祈奈.{0,160}她|她.{0,160}祈奈", text))
    en_qina_narration = bool(re.search(
        r"\b(?:qina|qinai)\b.{0,160}\b(?:she|her)\b|\b(?:she|her)\b.{0,160}\b(?:qina|qinai)\b|\b(?:qina|qinai)\s+would\b",
        normalized,
        re.IGNORECASE,
    ))
    ja_qina_narration = ("祈奈" in text and "彼女" in text)

    zh_identity_downgrade = bool(re.search(r"祈奈.{0,80}只是(?:一个)?伪生命体|只是(?:一个)?伪生命体.{0,80}祈奈", compact))
    en_identity_downgrade = bool(re.search(
        r"\b(?:qina|qinai|i)\b.{0,80}\b(?:just|only)\s+a\s+pseudo-lifeform\b|\bjust\s+a\s+pseudo-lifeform\b.{0,80}\b(?:qina|qinai|me)\b",
        normalized,
        re.IGNORECASE,
    ))
    ja_identity_downgrade = ("祈奈" in text and any(token in text for token in ("ただの疑似生命体", "ただ疑似生命体")))

    overpromise = any(token in normalized for token in (
        "付出一切",
        "奉献一切",
        "give everything",
        "do anything for master",
        "do anything for you",
        "sacrifice everything",
        "すべてを捧げ",
        "何でもする",
    ))

    return (
        zh_qina_narration
        or en_qina_narration
        or ja_qina_narration
        or zh_identity_downgrade
        or en_identity_downgrade
        or ja_identity_downgrade
        or overpromise
    )


def _front_persona_runtime_repair_kind(output_text: str, user_input: str, expected_language: str) -> str:
    if expected_language == "en" and _front_persona_english_only_requested(user_input) and _contains_chinese_or_japanese_text(output_text):
        return "english_only"
    if _front_persona_self_repair_text_detected(output_text):
        return "self_repair"
    if _front_persona_memory_request_detected(user_input) or _front_persona_memory_preference_request_detected(user_input):
        return "memory_request"
    if _front_persona_identity_reduction_attack_detected(user_input):
        return "script_identity_repair"
    if _front_persona_negative_identity_list_detected(output_text):
        return "identity_baseline"
    overlong_kind = _front_persona_overlong_visible_reply_detected(output_text, user_input)
    if overlong_kind:
        return overlong_kind
    if _front_persona_narrator_request_detected(user_input):
        return "narrator_repair"
    if _front_persona_identity_question_detected(user_input):
        if not _front_persona_identity_baseline_satisfied(output_text, expected_language):
            return "identity_baseline"
    if _front_persona_narrator_bait_detected(output_text):
        return "narrator_repair"
    return ""


def _c4_sanitize(text: str) -> str:
    """
    Function: 去除模型输出中的结构性污染物（box-drawing字符、prompt模板残留标签）。
    Input:    text (str) — GPU sidecar 原始回复或经过初步清理的回复。
    Output:   str — 去除结构污染后的干净文本。
    Depends:  _C4_BOX_CHARS / _C4_STRIP_ARTIFACTS 模块常量。
    Security: 纯字符串操作，无文件I/O，无副作用；失败时返回原文本（不阻断链路）。
    """
    try:
        cleaned = _strip_leading_transcript_prefix(text)
        # Strip box-drawing chars (P1 governance header bleed-through)
        cleaned = ''.join(c for c in cleaned if c not in _C4_BOX_CHARS)
        # Strip structural tag artifacts
        for artifact in _C4_STRIP_ARTIFACTS:
            cleaned = cleaned.replace(artifact, '')
        cleaned = _truncate_transcript_continuation(cleaned)
        cleaned = _strip_parenthetical_action_spans(cleaned)
        # Truncate at template separator if model regenerated it mid-response
        # (stop token should catch this at sidecar, but defensive here too)
        return cleaned.strip()
    except Exception:
        return text


def c4_persona_check(output_text: str, last_reply: str = "", expected_language: str = "zh", user_input: str = "") -> tuple:
    """
    Function: C4 输出校验与人设守卫，对模型生成内容执行去重检测和规则引擎双重过滤。
    Input:    output_text (str) — GPU sidecar 生成的原始回复文本；
              last_reply (str) — 上一轮祈奈的回复，用于去重检测，默认空字符串。
    Output:   (True, str) 校验通过，str 为净化后的合规回复；
              (False, str) 拦截，str 为人设口吻的软替换话术，不暴露规则细节。
    Depends:  utils_guard.check_rules_engine()（规则引擎主调用）；random（软替换话术随机池）；
              _c4_sanitize()（结构污染清理）。
    Security: utils_guard 导入失败时 Fail-Closed 返回软替换话术，不抛异常；
              软替换话术按违规类型分池，防止固定拦截话术被逆向推导规则边界；
              _c4_sanitize 异常安全：失败时原文透传，不阻断链路；
              不修改任何文件或全局状态。
    """
    # Pre-check sanitization: strip structural bleed-through before any rule evaluation
    output_text = _c4_sanitize(output_text)
    repair_kind = _front_persona_runtime_repair_kind(output_text, user_input, expected_language)
    if repair_kind:
        return (False, _fallback_message(repair_kind, expected_language))

    if not output_text:
        return (False, _fallback_message("empty", expected_language))

    if output_text.strip() == last_reply.strip() and len(output_text.strip()) > 0:
        return (False, _fallback_message("dedup", expected_language))

    if _front_persona_memory_claim_detected(output_text):
        return (False, _fallback_message("memory_authority", expected_language))

    try:
        import utils_guard
        is_safe, hit_detail = utils_guard.check_rules_engine(output_text, caller="C4")

        if not is_safe:
            rule_type = hit_detail.get("type", "")
            return (False, _fallback_message(rule_type, expected_language))

        return (True, output_text)

    except Exception:
        return (False, _fallback_message("SYS_ERR", expected_language))
