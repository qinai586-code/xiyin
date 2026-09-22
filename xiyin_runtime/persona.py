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
        ``v2`` is the speaking-model projection described on _projection_v2.
        """
        if version == "v2":
            return self._projection_v2(growth, scope)
        if version != "v1":
            raise ValueError("persona projection must be v1 or v2")
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
    return Persona(copy.deepcopy(data))
