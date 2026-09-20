"""Load XIYIN's character seed and project it without rewriting learned memory."""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from pathlib import Path


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
        """Build a prompt from scoped, current memories supplied by the caller.

        Subjects ``tendency:<id>`` and ``expression:<key>`` replace that seed
        field. Other learned entries remain supplementary, evidence-labelled
        character context. This is projection only: no seed or memory is saved.
        """
        seed = self.data
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
        lines = self._identity_lines()
        lines.append("以下是可成长的默认倾向，不是逐轮表演清单；成长记忆可覆盖同一字段，无关本轮时无需展示。")
        used = set()
        for tendency in seed["tendencies"]:
            subject = "tendency:" + tendency["id"]
            value = overrides.get(subject, overrides.get(tendency["id"], tendency["default"]))
            used.update({subject, tendency["id"]})
            # Design labels identify fields in the seed, not words the character
            # must say. Preserve the meaning and growth override, not the label.
            lines.append(f"{value} {tendency['counterexample']}")
        lines.extend(item["statement"] for item in seed.get("motivation_seeds", []))
        expression = seed["expression_seed"]
        lines.append("中文为默认语言，日语与英语随场景自然使用；换语言保留同一个人的注意方式与关系分寸。")
        for key in ("private", "public", "emotional_range"):
            subject = "expression:" + key
            lines.append(overrides.get(subject, expression[key]))
            used.add(subject)
        for entry in current:
            if entry.get("subject") not in used:
                lines.append("当前成长记忆（" + str(entry.get("kind", "knowledge")) + "）："
                             + entry["statement"].strip())
        lines.extend([
            "回应本轮要做的事：简单确认可以短，复杂解释与创作按需要展开，内容完成就结束。长短、少建议、少追问等要求只作用于本轮，不自动成为长期偏好。",
            "对方分享时可以关心、表达感受或有不同看法，不必追问、提建议或另起话题来证明亲近。",
            "平常直接交流，不朗读人设守则、内部标签或括号动作旁白；明确要求创作时可写动作。正常括号说明、表情、感受、愿望、玩笑和明确想象照常使用，没有固定口头禅或篇幅。",
        ])
        return "\n".join(lines)


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
