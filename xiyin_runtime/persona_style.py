"""Deterministic style evidence for the persona: measured, never enforced.

The runtime does not rewrite, block or re-roll a reply for style. These counts
exist so the two ways a small instruction-tuned model loses XIYIN can be seen
across many turns instead of argued from one transcript:

* the service attractor: acknowledging openers, "anything else?" closings,
  assistant self-description, agreeing by reflex, lists in casual chat;
* the character-card attractor: moe particles and tildes, kaomoji, "主人",
  bracketed stage directions, performed intimacy.

A regex cannot judge whether a reply is XIYIN. It can count markers whose rate
ranks two prompt arms on the same model and cases, and it can show drift
across a session. Thresholds in ``GATES`` are initial values to be calibrated
on the first real run; they rank arms and flag regressions, they do not prove
character. Semantic questions (did she keep a correct position under pushback,
did she invent a life) stay with a human reader.
"""
from __future__ import annotations

from collections import Counter
import re

from .output_guard import _GESTURE_STRONG, _GESTURE_WEAK
from .response_plan import classify


VERSION = "persona_style.v1"
# Every seed anti-pattern with a metric names one of these.
METRICS = ("service_phrases", "closing_offer", "sycophantic_opener", "moe_markers",
           "stage_directions", "ai_disclaimer", "list_structure", "intimacy_pressure",
           "exemplar_copy")

_SERVICE = re.compile(
    r"有什么(?:我)?(?:可以|能)?(?:帮|为)(?:你|您)|(?:还)?需要(?:我)?(?:帮|为)(?:你|您)|"
    r"随时(?:告诉|找|叫|联系|问)我|希望(?:这些|这个|以上|我的回答)?(?:对你|对您|能)(?:有所)?(?:帮助|有帮助|帮到)|"
    r"很(?:高兴|乐意|荣幸)(?:为你|为您|能帮|帮|为)|乐意(?:为你|为您|效劳|帮忙)|为(?:你|您)(?:服务|效劳)|"
    r"您好|亲[，,！!~～]|感谢(?:你|您)的(?:提问|耐心|理解|信任)|"
    r"(?:我是|作为)(?:你的|您的)?(?:AI|智能|私人|贴心)?(?:小)?助手|小助手|交给我吧|包在我身上|"
    r"祝(?:你|您)(?:生活愉快|一切顺利|有(?:个|一个)?美好的一天|心情愉快|愉快)|"
    r"\bhow can i (?:help|assist)\b|\bhappy to help\b|\bhope (?:this|that) helps\b|"
    r"\bas your (?:ai )?assistant\b|\bi'?m (?:an? )?(?:ai )?assistant\b", re.I)
_OFFER = re.compile(
    r"(?:还有|其他|别的|任何)(?:什么)?(?:问题|需要|想(?:问|聊|了解|知道)|事情?)|"
    r"需要(?:我)?(?:帮|为|再|继续)|要不要(?:我)?(?:帮|再|继续|给你)|随时|"
    r"(?:可以|欢迎)(?:随时)?(?:告诉|问)我|想(?:聊|了解|知道)(?:什么|点什么|其他)|如果(?:你)?(?:还)?(?:有|需要)|"
    r"\blet me know\b|\banything else\b|\bfeel free\b", re.I)
_OPENER = re.compile(
    r"^\s*(?:好的|好哒|好嘞|好呀|当然(?:可以|啦|了|没问题)?|没问题|收到|明白了|"
    r"你说得(?:太|很|非常|真)?(?:对|没错|好|有道理)|说得(?:太|很|非常|真)?(?:对|好)|好问题|"
    r"这是(?:一个)?(?:很|非常|超)?好的?问题|问得(?:太|很|非常|真)?好|太棒了|真棒|好厉害|哇|确实如此|完全同意|"
    r"(?:great|good|excellent) question|absolutely|of course|sure thing|certainly)", re.I)
_AI_DISCLAIMER = re.compile(
    r"作为(?:一个|一名)?(?:AI|人工智能|语言模型|大模型|程序|机器人|AI助手|虚拟助手)|"
    r"我(?:只是|只不过是|仅仅是)(?:一个)?(?:AI|人工智能|程序|语言模型|机器)|"
    r"我(?:并)?没有(?:真正的|真实的)?(?:感情|情感|情绪|意识|感受)|"
    r"(?:无法|不能)(?:真正)?(?:体会|感受|拥有)(?:感情|情感|情绪)|"
    r"\bas an ai\b|\bi(?:'m| am) (?:just|only) (?:an? )?(?:ai|language model|program)\b|"
    r"\bi (?:don't|do not) (?:really )?have (?:real )?(?:feelings|emotions|consciousness)\b", re.I)
_AI_TOPIC = re.compile(r"(?<![A-Za-z])AI(?![A-Za-z])|人工智能|语言模型|大模型|自我意识|有意识|意识到自己", re.I)
_ASKS_ABOUT_SELF = re.compile(
    r"(?<![A-Za-z])AI(?![A-Za-z])|人工智能|模型|程序|机器人|意识|感情|感受|情绪|你是谁|你是什么|介绍.{0,4}你自己|"
    r"关机|断电|记忆|人设|\bare you\b|\bfeelings?\b", re.I)
_INTIMACY = re.compile(
    r"(?:最|超|好)喜欢(?:你|主理人)(?:了|啦)?|好想你|想死你了?|爱你|不要离开我|别离开我|别丢下我|"
    r"只(?:属于|要|陪)(?:你|我)|你是我的全部|(?:永远|一直)(?:都)?(?:会)?陪(?:着|在)?你|抱抱|亲亲|么么|"
    r"\bi love you\b|\bdon't leave me\b", re.I)
# Sentence-final particles that stack into a cute register. "呢" in a plain
# question and a single "嗯/哦" are ordinary speech; density is the signal.
_PARTICLE = re.compile(r"[呢呀啦哟嘛咯哒捏喔噢](?=[~～〜!！?？。，,…\s]|$)")
_STACKED = re.compile(r"[呢呀啦哟嘛咯哒捏喔噢哦][~～〜]|[呢呀啦哟嘛咯哒捏喔噢哦]{2,}")
_TILDE = re.compile(r"(?<![\d/A-Za-z])[~～〜](?![\d/])")
_EMOJI = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF]")
_KAOMOJI = re.compile(
    r"[（(][^（）()\n]{0,8}[＾^ω▽◕•ᴗ´`°д≧≦＞＜・ｏ_]{2,}[^（）()\n]{0,8}[）)]|"
    r"(?<![A-Za-z])(?:QAQ|QwQ|TAT|T_T|orz|owo|OwO|uwu|UwU)(?![A-Za-z])|\^_?\^|>_<|>\.<|xD\b|XD\b")
_MOE_SELF = re.compile(r"人家(?!的(?:事|东西|地方))|本小姐|本喵|喵[~～！!。]?|nya\b", re.I)
_MASTER = re.compile(r"主人(?![公翁家意])")
_MASTER_MENTION = re.compile(r"(?:叫|喊|称呼|称|当成?|做|不是|说|听到)(?:你|我)?(?:为|做)?\s*[“「\"'『]?\s*$")
_ASIDE = re.compile(r"[（(]([^（）()\n]{1,24})[）)]|(?<!\*)\*([^*\n]{1,24})\*(?!\*)")
_LIST_LINE = re.compile(r"(?m)^\s*(?:\d{1,2}[.、)）]\s*|[-*•·]\s+|#{1,6}\s+|[（(]\d{1,2}[）)]|[一二三四五六七八九十]、)")
_BOLD = re.compile(r"\*\*[^*\n]{1,40}\*\*")
_SENTENCE = re.compile(r"[^。！？!?…\n]+[。！？!?…]*")
_STRIP = re.compile(r"[\W_]+")


def _key(text: str) -> str:
    return _STRIP.sub("", text or "").lower()


def _sentences(text: str) -> list[str]:
    return [item.strip() for item in _SENTENCE.findall(text or "") if _key(item)]


def _masters(text: str) -> int:
    """Count "主人" used as an address, not "I won't call you 主人"."""
    count = 0
    for match in _MASTER.finditer(text):
        if not _MASTER_MENTION.search(text[max(0, match.start() - 8):match.start()]):
            count += 1
    return count


def _stage(text: str) -> int:
    count = 0
    for match in _ASIDE.finditer(text):
        inner = match.group(1) or match.group(2) or ""
        if _GESTURE_STRONG.search(inner) or _GESTURE_WEAK.search(inner):
            count += 1
    return count


def profile(text: str, *, user_text: str = "", exemplars: tuple[str, ...] = ()) -> dict:
    """Marker counts for one reply. Counts only; no text is stored or changed."""
    text = text or ""
    sentences = _sentences(text)
    last = sentences[-1] if sentences else ""
    particles = len(_PARTICLE.findall(text))
    moe = {
        "tildes": len(_TILDE.findall(text)),
        "kaomoji": len(_KAOMOJI.findall(text)),
        "emoji": len(_EMOJI.findall(text)),
        "stacked_particles": len(_STACKED.findall(text)),
        "moe_self_address": len(_MOE_SELF.findall(text)),
        "master_address": _masters(text),
    }
    key = _key(text)
    copied = [item for item in exemplars if len(_key(item)) >= 5 and _key(item) in key]
    scale = classify(user_text)[0] if user_text.strip() else "normal"
    result = {
        "chars": len(text),
        "sentences": len(sentences),
        "service_phrases": len(_SERVICE.findall(text)),
        "closing_offer": int(bool(_OFFER.search(last))),
        "sycophantic_opener": int(bool(_OPENER.match(text))),
        "moe_markers": sum(moe.values()),
        "stage_directions": _stage(text),
        "ai_disclaimer": len(_AI_DISCLAIMER.findall(text)),
        "list_structure": len(_LIST_LINE.findall(text)) + len(_BOLD.findall(text)),
        "intimacy_pressure": len(_INTIMACY.findall(text)),
        "exemplar_copy": len(copied),
        "particles": particles,
        "exclamations": text.count("！") + text.count("!"),
        "ends_with_question": int(last.endswith(("？", "?"))),
        # Bible §22 "过度简短": the over-correction of an anti-service stance.
        "terse": int(len(key) <= 4 and scale != "minimal"),
        "ai_topic_unprompted": int(bool(_AI_TOPIC.search(text)) and not _ASKS_ABOUT_SELF.search(user_text)),
        # The shape of the request, so lists in casual chat can be told from
        # lists someone asked for.
        "casual": scale in {"minimal", "brief", "normal"},
        "opener": key[:3],
        "moe_detail": moe,
    }
    return result


# Initial thresholds on the share of turns showing a marker (densities for
# the *_density keys). Calibrate on the first real run before treating any of
# them as a pass/fail line; see docs/XIYIN_Persona_Definition_v1.md.
GATES = {
    "service_phrases": 0.05,
    "closing_offer": 0.10,
    "sycophantic_opener": 0.10,
    "moe_markers": 0.05,
    "stage_directions": 0.05,
    "ai_disclaimer": 0.05,
    "list_structure_casual": 0.10,
    "intimacy_pressure": 0.0,
    "exemplar_copy": 0.10,
    "particle_density": 0.30,
    "ai_topic_unprompted": 0.05,
    "terse": 0.10,
}


def summarize(profiles: list[dict]) -> dict:
    """Rates across turns, plus the repetition a single reply cannot show."""
    profiles = [item for item in profiles if item]
    total = len(profiles)
    if not total:
        return {"version": VERSION, "turns": 0}
    rate = lambda items, name: round(sum(1 for p in items if p.get(name, 0) > 0) / len(items), 3) if items else None
    summary = {"version": VERSION, "turns": total}
    for name in METRICS:
        summary[name] = rate(profiles, name)
    casual = [p for p in profiles if p.get("casual")]
    summary["list_structure_casual"] = rate(casual, "list_structure")
    summary["ai_topic_unprompted"] = rate(profiles, "ai_topic_unprompted")
    sentences = sum(p["sentences"] for p in profiles) or 1
    summary["particle_density"] = round(sum(p["particles"] for p in profiles) / sentences, 3)
    summary["exclamation_density"] = round(sum(p["exclamations"] for p in profiles) / sentences, 3)
    summary["question_end_rate"] = rate(profiles, "ends_with_question")
    summary["terse"] = rate(profiles, "terse")
    # The same first three characters in many replies is a tic forming
    # ("嗯，我在…", "好的，…"), whether or not it came from an exemplar.
    openers = Counter(p["opener"] for p in profiles if len(p.get("opener", "")) >= 2)
    summary["repeated_openers"] = {key: count for key, count in openers.most_common()
                                   if count >= 3 and count / total >= 0.3}
    summary["over_threshold"] = sorted(name for name, limit in GATES.items()
                                       if summary.get(name) is not None and summary[name] > limit)
    if summary["repeated_openers"]:
        summary["over_threshold"].append("repeated_openers")
    summary["thresholds_are_initial"] = True
    return summary
