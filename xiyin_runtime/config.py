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
    return Settings(
        provider=ProviderConfig(
            endpoint=inference["endpoint"],
            model=inference.get("model", "xiyin"),
            timeout_seconds=inference.get("timeout_seconds", 60),
            max_tokens=inference.get("max_tokens", 512),
            enable_thinking=inference.get("enable_thinking", False),
        ),
        persona_path=xiyin_paths.resolve_path("character_seed"),
        **values,
    )
