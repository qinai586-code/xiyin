"""Read code-owned configuration without creating data or contacting a model."""

from dataclasses import dataclass
from pathlib import Path
import tomllib

import xiyin_paths
from .provider import ProviderConfig


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
    # stay selectable for A/B and rollback.
    persona_projection: str = "v3"


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
    projection = foundation.get("persona_projection", "v3")
    if projection not in {"v1", "v2", "v3"}:
        raise ValueError("foundation.persona_projection must be v1, v2 or v3")
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
        ),
        persona_path=xiyin_paths.resolve_path("character_seed"),
        idle_sleep_seconds=idle_sleep,
        persona_projection=projection,
        **values,
    )
