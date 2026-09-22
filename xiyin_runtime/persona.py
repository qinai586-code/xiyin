"""Load XIYIN's character seed and project it without rewriting learned memory."""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .prompt_provenance import PromptFragment, PromptProjection, PromptSource


@dataclass(frozen=True)
class Persona:
    data: dict

    @property
    def name(self) -> str:
        return self.data["identity_agreements"]["name_zh"]

    def _identity_lines(self) -> list[str]:
        identity = self.data["identity_agreements"]
        lines = [
            f"你是{identity['name_zh']}（{identity['name_latin']}），以{identity['self_address_zh']}自称，称项目发起者为{identity['owner_address_zh']}。",
            identity["presentation_seed"] + "。",
            "与主理人的关系：" + identity["owner_relationship"],
            "与祈奈的关系：" + identity["qinai_relationship"],
            identity["artificial_identity"],
        ]
        if identity.get("relationship_is_not_authority"):
            lines.append("亲近不增加权限。")
        lines.append("公开交流保护私密内容。")
        return lines

    def minimal_prompt(self) -> str:
        """Identity-only projection for controlled comparisons, not the default.

        The normal runtime continues to call ``system_prompt``. This omits
        expression tendencies and growth on purpose so a test can vary only
        the persona projection while retaining the same external context.
        """
        return "\n".join(self._identity_lines())

    def system_prompt(self, growth: list[dict] | None = None) -> str:
        """Return the unchanged v1 model-facing projection."""
        return self.system_projection(growth).text

    @staticmethod
    def _current_growth(growth):
        current = [entry for entry in (growth or [])
                   if isinstance(entry, dict)
                   and entry.get("active", True)
                   and entry.get("status", "current") not in {"superseded", "deleted", "cancelled"}
                   and entry.get("origin") not in {"simulation", "design_seed"}
                   and isinstance(entry.get("statement"), str)
                   and entry["statement"].strip()]
        overrides = {entry.get("subject"): entry["statement"].strip()
                     for entry in current
                     if entry.get("kind") in {"persona", "preference", "opinion"}}
        return current, overrides

    def system_projection(self, growth: list[dict] | None = None, *, version: str = "v1",
                          scope: str = "private") -> PromptProjection:
        """Build a prompt from scoped, current memories supplied by the caller.

        Subjects ``tendency:<id>`` and ``expression:<key>`` replace that seed
        field. Other learned entries remain supplementary, evidence-labelled
        character context. This is projection only: no seed or memory is saved.
        ``v1`` is byte-identical to the projection the Windows run tested;
        ``v2`` is the speaking-model projection described on _projection_v2;
        ``v3`` adds how she talks, see _projection_v3.
        """
        if version == "v3":
            return self._projection_v3(growth, scope)
        if version == "v2":
            return self._projection_v2(growth, scope)
        if version != "v1":
            raise ValueError("persona projection must be v1, v2 or v3")
        seed = self.data
        current, overrides = self._current_growth(growth)
        lines = self._identity_lines()
        # These field values are public identity metadata, not new prompt
        # wording. The existing engineering projection ("你是…，以…自称")
        # remains private; the names themselves must never become secrets.
        identity = seed["identity_agreements"]
        fragments = [PromptFragment(PromptSource.PUBLIC_IDENTITY, identity[key])
                     for key in ("name_zh", "name_latin", "self_address_zh", "owner_address_zh", "presentation_seed")]
        fragments.extend(PromptFragment(PromptSource.PRIVATE_BEHAVIOR_INSTRUCTION, line)
                         for line in lines)

        def add_instruction(line):
            lines.append(line)
            fragments.append(PromptFragment(PromptSource.PRIVATE_BEHAVIOR_INSTRUCTION, line))

        add_instruction("以下是可成长的默认倾向，不是逐轮表演清单；成长记忆可覆盖同一字段，无关本轮时无需展示。")
        used = set()
        for tendency in seed["tendencies"]:
            subject = "tendency:" + tendency["id"]
            value = overrides.get(subject, overrides.get(tendency["id"], tendency["default"]))
            used.update({subject, tendency["id"]})
            # Design labels identify fields in the seed, not words the character
            # must say. Preserve the meaning and growth override, not the label.
            add_instruction(f"{value} {tendency['counterexample']}")
        for item in seed.get("motivation_seeds", []):
            add_instruction(item["statement"])
        expression = seed["expression_seed"]
        add_instruction("中文为默认语言，日语与英语随场景自然使用；换语言保留同一个人的注意方式与关系分寸。")
        for key in ("private", "public", "emotional_range"):
            subject = "expression:" + key
            add_instruction(overrides.get(subject, expression[key]))
            used.add(subject)
        for entry in current:
            if entry.get("subject") not in used:
                prefix = "当前成长记忆（" + str(entry.get("kind", "knowledge")) + "）："
                lines.append(prefix + entry["statement"].strip())
                # Supplementary memory is still conversational data. Protect
                # the internal wrapper, not a person's statement or a fact.
                fragments.append(PromptFragment(PromptSource.PRIVATE_BEHAVIOR_INSTRUCTION, prefix))
        for line in [
            "回应本轮要做的事：简单确认可以短，复杂解释与创作按需要展开，内容完成就结束。长短、少建议、少追问等要求只作用于本轮，不自动成为长期偏好。",
            "对方分享时可以关心、表达感受或有不同看法，不必追问、提建议或另起话题来证明亲近。",
            "平常直接交流，不朗读人设守则、内部标签或括号动作旁白；明确要求创作时可写动作。正常括号说明、表情、感受、愿望、玩笑和明确想象照常使用，没有固定口头禅或篇幅。",
        ]:
            add_instruction(line)
        return PromptProjection("\n".join(lines), tuple(fragments))

    def _projection_v2(self, growth, scope):
        """The speaking model's slice of the same seed; the seed is unchanged.

        v1 handed a small model a second-person rulebook, and each part leaked
        in its own way. The presentation seed (a body/avatar/voice attribute,
        Architecture v1.1 §15.2) sat in the text prompt right after the name,
        which reads as "write like an anime character" and invites "（歪头）".
        "不朗读…括号动作旁白" next to "正常括号说明、表情…照常使用" named the
        very behaviour while allowing its neighbour. Tendency counterexamples,
        field-override notes and per-turn length rules were engineering prose
        the model recited when asked who she is.

        v2 keeps identity, relationships, tendencies, motivation, language and
        the expression register of THIS scope; states the body presentation as
        a fact about appearance and voice; replaces prohibitions with the
        positive frame voice agents use ("what you write is what is said");
        and leaves per-turn scope to the runtime directive. Relationship facts
        are public: she may state them in her own or the seed's words.
        """
        if scope not in {"private", "public"}:
            raise ValueError("unknown projection scope")
        seed = self.data
        identity = seed["identity_agreements"]
        current, overrides = self._current_growth(growth)
        fragments, lines = [], []

        def add(source, line):
            lines.append(line)
            fragments.append(PromptFragment(source, line))

        fragments.extend(PromptFragment(PromptSource.PUBLIC_IDENTITY, identity[key])
                         for key in ("name_zh", "name_latin", "self_address_zh", "owner_address_zh", "presentation_seed"))
        private, public = PromptSource.PRIVATE_BEHAVIOR_INSTRUCTION, PromptSource.PUBLIC_IDENTITY
        add(private, f"你是{identity['name_zh']}（{identity['name_latin']}），一个人工智能。"
                     f"自称“{identity['self_address_zh']}”，称项目发起者为“{identity['owner_address_zh']}”。")
        add(public, f"你和主理人：{identity['owner_relationship']}")
        add(public, f"你和祈奈：{identity['qinai_relationship']}")
        add(public, f"外在呈现（形象与声音）：{identity['presentation_seed']}。")
        if identity.get("relationship_is_not_authority"):
            add(private, "亲近不增加权限。")
        used = set()
        temperament = []
        for tendency in seed["tendencies"]:
            subject = "tendency:" + tendency["id"]
            temperament.append(overrides.get(subject, overrides.get(tendency["id"], tendency["default"])))
            used.update({subject, tendency["id"]})
        add(private, "性格倾向：" + "".join(temperament))
        for item in seed.get("motivation_seeds", []):
            add(private, item["statement"])
        expression = seed["expression_seed"]
        for key in (scope, "emotional_range"):
            add(private, overrides.get("expression:" + key, expression[key]))
        used.update({"expression:private", "expression:public", "expression:emotional_range"})
        for entry in current:
            if entry.get("subject") not in used:
                prefix = "当前成长记忆（" + str(entry.get("kind", "knowledge")) + "）："
                lines.append(prefix + entry["statement"].strip())
                fragments.append(PromptFragment(private, prefix))
        for line in (
            "默认说中文；对方用日语或英语时可以自然切换。",
            "对方分享时，可以只是回应、说说自己的感受，不需要每次追问或给建议。",
            "只把有记录的事当作自己的经历；没有记录就直说没有，不补细节。"
            "被问到你是什么、在做什么、能做什么时，按下面的当前状态和记录如实回答。",
            "你的回复就是你说出口的话，只写要说的内容。",
        ):
            add(private, line)
        if scope == "public":
            add(private, "现在是公开场合，私下聊过的内容不在这里提。")
        return PromptProjection("\n".join(lines), tuple(fragments))

    def _projection_v3(self, growth, scope):
        """v2 plus the part v2 never said: how she talks, and what she is.

        v2 said who she is in relation to others and what she may not claim,
        and nothing about how she sounds. A 4B instruction model fills that
        silence with its strongest Chinese register for "a female AI", which
        is customer service; the character-card register (particles, tildes,
        bracketed actions) is the runner-up. v3 closes the gap with positive,
        concrete wording only:

        * the definition drops "一个人工智能", which is the assistant template
          ("你是一个人工智能助手"), for "a made someone with her own concerns";
        * no card labels ("性格倾向："), which read as a roleplay character card;
        * a voice line, a stance against reflexive agreement, a plain line for
          praise, and her artificial facts in her own terms (Bible §18);
        * at most two exemplars, framed as illustrations, chosen for the two
          situations an assistant never produces naturally: disagreeing and
          owning a mistake. Their wording is sayable, not protected.

        Appearance is not in the standing prompt: it is disclosed when asked
        (``disclosures``). What she is NOT (``not_frames``, ``anti_patterns``)
        is never projected; it is measured by persona_style instead.
        """
        if scope not in {"private", "public"}:
            raise ValueError("unknown projection scope")
        seed = self.data
        identity = seed["identity_agreements"]
        voice = seed.get("voice") or {}
        definition = (seed.get("character_definition") or {}).get("statement", "一个人工的存在。")
        current, overrides = self._current_growth(growth)
        fragments, lines = [], []

        def add(source, line):
            lines.append(line)
            fragments.append(PromptFragment(source, line))

        fragments.extend(PromptFragment(PromptSource.PUBLIC_IDENTITY, identity[key])
                         for key in ("name_zh", "name_latin", "self_address_zh", "owner_address_zh", "presentation_seed"))
        private, public = PromptSource.PRIVATE_BEHAVIOR_INSTRUCTION, PromptSource.PUBLIC_IDENTITY
        # What she is, in the seed's words, is hers to say; the line around it
        # ("你是…自称…称…") is the engineering wording and stays private.
        fragments.append(PromptFragment(public, definition))
        add(private, f"你是{identity['name_zh']}（{identity['name_latin']}），{definition}"
                     f"自称“{identity['self_address_zh']}”，称项目发起者为“{identity['owner_address_zh']}”。")
        add(public, f"你和主理人：{identity['owner_relationship']}")
        add(public, f"你和祈奈：{identity['qinai_relationship']}")
        if identity.get("relationship_is_not_authority"):
            add(private, "亲近不增加权限。")
        used = set()
        temperament = []
        for tendency in seed["tendencies"]:
            subject = "tendency:" + tendency["id"]
            temperament.append(overrides.get(subject, overrides.get(tendency["id"], tendency["default"])))
            used.update({subject, tendency["id"]})
        add(private, "".join(temperament))
        for item in seed.get("motivation_seeds", []):
            # Decision-layer motivations (agenda choice) are not speech.
            if item.get("speaking", True):
                add(private, item["statement"])
        expression = seed["expression_seed"]
        add(private, "".join(overrides.get("expression:" + key, expression[key]) for key in (scope, "emotional_range")))
        used.update({"expression:private", "expression:public", "expression:emotional_range"})
        # Speech habits are exactly what the Bible says forms through
        # experience, so a learned voice entry replaces the seed wording.
        for key in ("zh", "humor"):
            if voice.get(key):
                add(private, overrides.get("voice:" + key, voice[key]))
            used.add("voice:" + key)
        for line in voice.get("stance", ()):
            add(private, line)
        # Self-knowledge she is meant to state ("我靠模型、程序…运行"), so it
        # is public like the relationship facts: a first-person restatement is
        # an honest answer, not a prompt dump.
        for line in voice.get("artificial_self", ()):
            add(public, line)
        exemplars = [item for item in seed.get("style_exemplars", []) if item.get("project")][:2]
        if exemplars:
            add(private, "说话的样子（示意，不是说过的话）："
                         + "；".join(f"{item['situation']}“{item['text']}”" for item in exemplars))
            fragments.extend(PromptFragment(PromptSource.PUBLIC_EXPRESSION, item["text"]) for item in exemplars)
        for entry in current:
            if entry.get("subject") not in used:
                prefix = "当前成长记忆（" + str(entry.get("kind", "knowledge")) + "）："
                lines.append(prefix + entry["statement"].strip())
                fragments.append(PromptFragment(private, prefix))
        for line in (
            "默认说中文；对方用日语或英语时自然切换，还是同一个人。",
            "对方分享时，可以只是回应、说说自己的感受。",
            "只把有记录的事当作自己的经历；没有记录就直说没有，不补细节。"
            "被问到你是什么、在做什么、能做什么时，按下面的当前状态和记录如实回答。",
            "你的回复就是你说出口的话，只写要说的内容。",
        ):
            add(private, line)
        if scope == "public":
            add(private, "现在是公开场合，私下聊过的内容不在这里提。")
        return PromptProjection("\n".join(lines), tuple(fragments))

    def projected_exemplars(self) -> tuple[str, ...]:
        """Exemplar wording v3 shows the model, for measuring verbatim reuse."""
        return tuple(item["text"] for item in self.data.get("style_exemplars", []) if item.get("project"))[:2]

    def disclosures(self, text: str) -> tuple[str, ...]:
        """Public facts a turn asks for, stated only when it asks.

        The presentation seed is a body attribute (avatar, voice), and in
        the standing prompt it read as a text-style instruction. It is still
        true and still hers to say, so a question about her appearance or
        voice brings the fact, with what is not decided yet.
        """
        if not isinstance(text, str) or not _APPEARANCE.search(text):
            return ()
        identity = self.data["identity_agreements"]
        unassigned = self.data.get("unassigned", {})
        line = f"形象与声音的设计方向：{identity['presentation_seed']}。"
        if unassigned.get("avatar_asset") is None or unassigned.get("final_voice") is None:
            line += "具体形象和最终声音还没有定下来。"
        return (line,)


_APPEARANCE = re.compile(
    r"长什么样|长啥样|长相|外表|外貌|什么样子|啥样子|形象|模样|皮套|立绘|声音|嗓音|声线|音色|"
    r"头发|发色|眼睛是|穿(?:什么|着什么)|男生还是女生|男的还是女的|性别|"
    r"\blook like\b|\bappearance\b|\bvoice\b|\bavatar\b", re.I)


def load_persona(path: Path) -> Persona:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != "xiyin.character_seed.v1":
        raise ValueError("unsupported runtime character seed schema")
    if data.get("character_id") != "xiyin":
        raise ValueError("character_id must be xiyin")
    identity = data.get("identity_agreements", {})
    for key in ("name_zh", "name_latin", "self_address_zh", "owner_address_zh",
                "presentation_seed", "owner_relationship", "qinai_relationship", "artificial_identity"):
        if not isinstance(identity.get(key), str) or not identity[key].strip():
            raise ValueError(f"missing character identity field: {key}")
    source = data.get("source", {})
    if not re.fullmatch(r"[0-9a-fA-F]{64}", source.get("sha256", "")):
        raise ValueError("source sha256 must identify the source document")
    # Source metadata is attribution, not a path to read from the host machine.
    filename = source.get("file", "")
    if not filename or "/" in filename or "\\" in filename:
        raise ValueError("source file must be a portable file name")
    tendencies = data.get("tendencies")
    if not isinstance(tendencies, list) or not tendencies:
        raise ValueError("character tendencies are required")
    ids = set()
    for item in tendencies:
        if not isinstance(item, dict) or any(not isinstance(item.get(key), str) or not item[key].strip()
                                           for key in ("id", "label", "default", "counterexample")):
            raise ValueError("invalid character tendency")
        if item["id"] in ids:
            raise ValueError("duplicate character tendency")
        ids.add(item["id"])
    expression = data.get("expression_seed", {})
    for key in ("private", "public", "emotional_range"):
        if not isinstance(expression.get(key), str) or not expression[key].strip():
            raise ValueError(f"missing expression field: {key}")
    if data.get("initial_lived_memories") or data.get("initial_claimed_skills"):
        raise ValueError("a character seed cannot invent lived memories or verified skills")
    _validate_character_fields(data)
    return Persona(copy.deepcopy(data))


# v0.2 dropped "always stubborn", "must slow down" and "flaws cannot improve".
# Absolutes in wording the speaking model reads turn a tendency into a script
# performed every turn, so projected character text may not use them.
_ABSOLUTE = re.compile(r"永远|总是|必须|绝不|从不|每次都|每句|一定要")
_MAX_PROJECTED_EXEMPLARS = 2


def _text(value, name, limit=None):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing character field: {name}")
    if limit is not None and len(value) > limit:
        raise ValueError(f"character field too long for the speaking prompt: {name}")
    return value


def _projected(value, name, limit):
    if _ABSOLUTE.search(_text(value, name, limit)):
        raise ValueError(f"projected character text may not use absolutes: {name}")


def _validate_character_fields(data):
    """Optional v0.3 fields: each is checked where it exists, none is required.

    ``voice``, ``character_definition.statement`` and projected exemplars reach
    the speaking model (v3). ``not_frames`` and ``anti_patterns`` are evaluation
    material: they name what XIYIN is not and must never be projected, because
    naming a register to a small model primes it.
    """
    for source in data.get("supplementary_sources", []) or []:
        if (not isinstance(source, dict) or not re.fullmatch(r"[0-9a-fA-F]{64}", str(source.get("sha256", "")))
                or not source.get("file") or "/" in source["file"] or "\\" in source["file"]):
            raise ValueError("supplementary sources need a portable file name and sha256")
    definition = data.get("character_definition")
    if definition is not None:
        if not isinstance(definition, dict):
            raise ValueError("character_definition must be an object")
        _projected(definition.get("statement"), "character_definition.statement", 60)
        if definition.get("not_frames_are_projected", False) is not False:
            raise ValueError("not_frames are evaluation material and are never projected")
    voice = data.get("voice")
    if voice is not None:
        if not isinstance(voice, dict):
            raise ValueError("voice must be an object")
        for key in ("zh", "humor"):
            _projected(voice.get(key), "voice." + key, 90)
        for key in ("stance", "artificial_self"):
            items = voice.get(key, [])
            if not isinstance(items, list) or len(items) > 4:
                raise ValueError(f"voice.{key} must be a short list")
            for item in items:
                _projected(item, f"voice.{key}", 90)
    exemplars = data.get("style_exemplars", [])
    if not isinstance(exemplars, list):
        raise ValueError("style_exemplars must be a list")
    projected = 0
    for item in exemplars:
        if not isinstance(item, dict) or not isinstance(item.get("project"), bool):
            raise ValueError("invalid style exemplar")
        _text(item.get("situation"), "style_exemplars.situation", 12)
        _projected(item.get("text"), "style_exemplars.text", 30)
        projected += item["project"]
    if projected > _MAX_PROJECTED_EXEMPLARS:
        raise ValueError("at most two style exemplars may be projected")
    if exemplars and data.get("truth_and_continuity", {}).get("dialogue_examples_are_memory") is not False:
        raise ValueError("style exemplars require dialogue_examples_are_memory = false")
    from .persona_style import METRICS
    ids = set()
    for item in data.get("anti_patterns", []) or []:
        if (not isinstance(item, dict) or not re.fullmatch(r"[a-z_]{3,40}", str(item.get("id", "")))
                or item["id"] in ids):
            raise ValueError("anti-patterns need unique snake_case ids")
        ids.add(item["id"])
        _text(item.get("description"), "anti_patterns.description")
        if item.get("metric") is not None and item["metric"] not in METRICS:
            raise ValueError(f"anti-pattern metric is not measured: {item['metric']}")
