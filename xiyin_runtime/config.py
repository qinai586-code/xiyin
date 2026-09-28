"""Read code-owned configuration without creating data or contacting a model."""

from dataclasses import dataclass
from pathlib import Path
import tomllib

import xiyin_paths
from .provider import ProviderConfig, sampling_pairs


@dataclass(frozen=True)
class Settings:
    provider: ProviderConfig
    persona_path: Path
    max_input_chars: int = 2000
    max_context_chars: int = 4500
    history_messages: int = 8
    idle_sleep_seconds: int = 300
    # v3 is the speaking-model projection with voice and stance; v2 and v1
    # (byte-identical to the projection the Windows acceptance run tested)
    # stay selectable for A/B and rollback. v4 is v3 with the per-turn
    # decision projection; it is an arm until the owner adopts it. v5 is the
    # identity-card-only ablation (owner-authorised offline experiment).
    persona_projection: str = "v3"
    # Phase B (owner rulings 2026-09-25): verify the whole reply before any of
    # it is released, one clean regeneration, then the runtime abstention.
    # Default off; turning it on is an experiment arm until the owner adopts it.
    verify_before_release: bool = False
    # Persona repair experiment switches (2026-09-28), each independently
    # testable and all off by default. They apply to the v4 projection only,
    # so every arm is "v4 plus these", comparable with the archived v4 runs.
    persona_experiment: frozenset = frozenset()


# attention: the decision layer turns the Bible's tendencies into a
#   conditional per-turn attention cue on sharing and opinion turns;
# self_facts_on_demand: "你靠模型、程序…" leaves the standing prompt and is
#   disclosed on turns asking about her nature;
# tool_menu_on_demand: the registered-interface menu appears on task turns only;
# no_universal_ending: the "说完就停…" line is no longer appended to every move.
PERSONA_EXPERIMENTS = frozenset({"attention", "self_facts_on_demand", "tool_menu_on_demand", "no_universal_ending"})


def parse_persona_experiment(values) -> frozenset:
    if isinstance(values, str):
        values = [item.strip() for item in values.split(",") if item.strip()]
    if not isinstance(values, (list, tuple, set, frozenset)) or not all(isinstance(v, str) for v in values):
        raise ValueError("persona_experiment.enabled must be a list of names")
    unknown = set(values) - PERSONA_EXPERIMENTS
    if unknown:
        raise ValueError("unknown persona experiment: " + ", ".join(sorted(unknown)))
    return frozenset(values)


def load_settings() -> Settings:
    path = xiyin_paths.under(xiyin_paths.project_root(), "config/runtime.toml")
    with path.open("rb") as stream:
        config = tomllib.load(stream)
    inference = config["inference"]
    foundation = config.get("foundation", {})
    values = {}
    for name, default, maximum in (("max_input_chars", 2000, 20000),
                                   ("max_context_chars", 4500, 100000),
                                   ("history_messages", 8, 100)):
        value = foundation.get(name, default)
        if type(value) is not int or not 1 <= value <= maximum:
            raise ValueError(f"Invalid foundation.{name}")
        values[name] = value
    if values["max_context_chars"] <= values["max_input_chars"]:
        raise ValueError("Context budget must leave space for character and history")
    idle_sleep = config.get("autonomy", {}).get("idle_sleep_seconds", 300)
    if type(idle_sleep) is not int or not 0 <= idle_sleep <= 86400:
        raise ValueError("autonomy.idle_sleep_seconds must be 0..86400")
    verify = config.get("integrity", {}).get("verify_before_release", False)
    if type(verify) is not bool:
        raise ValueError("integrity.verify_before_release must be true or false")
    experiment = parse_persona_experiment(config.get("persona_experiment", {}).get("enabled", []))
    projection = foundation.get("persona_projection", "v3")
    if projection not in {"v1", "v2", "v3", "v4", "v5"}:
        raise ValueError("foundation.persona_projection must be v1, v2, v3, v4 or v5")
    return Settings(
        provider=ProviderConfig(
            endpoint=inference["endpoint"],
            model=inference.get("model", "xiyin"),
            timeout_seconds=inference.get("timeout_seconds", 60),
            max_tokens=inference.get("max_tokens", 512),
            enable_thinking=inference.get("enable_thinking", False),
            max_tokens_ceiling=inference.get("max_tokens_ceiling", 1792),
            max_timeout_seconds=inference.get("max_timeout_seconds", 600),
            context_tokens=inference.get("context_tokens", 4096),
            default_tokens_per_second=inference.get("default_tokens_per_second", 8.0),
            sampling=sampling_pairs(inference.get("sampling", {})),
        ),
        persona_path=xiyin_paths.resolve_path("character_seed"),
        idle_sleep_seconds=idle_sleep,
        persona_projection=projection,
        verify_before_release=verify,
        persona_experiment=experiment,
        **values,
    )
