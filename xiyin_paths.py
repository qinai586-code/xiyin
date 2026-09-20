"""Resolve XIYIN-owned paths without configuring or starting a runtime host."""

from pathlib import Path, PurePosixPath, PureWindowsPath
import tomllib


_WINDOWS_DEVICES = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {
    prefix + suffix
    for prefix in ("COM", "LPT")
    for suffix in "123456789¹²³"
}


def _inside(root: Path, path: Path) -> Path:
    resolved = path.resolve(strict=False)
    if not resolved.is_relative_to(root):
        raise ValueError("Path escapes XIYIN_ROOT")
    return resolved


def project_root() -> Path:
    root = Path(__file__).resolve().parent
    marker = _inside(root, root / ".xiyin_root")
    if not marker.is_file():
        raise FileNotFoundError("Missing .xiyin_root")
    return root


def resolve_path(name: str) -> Path:
    root = project_root()
    config = _inside(root, root / "config" / "paths.toml")
    with config.open("rb") as stream:
        value = tomllib.load(stream)["paths"][name]
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Expected a nonempty relative path")
    portable = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        "\\" in value
        or "\x00" in value
        or windows.drive
        or windows.root
        or ".." in portable.parts
        or any(ord(char) < 32 or char in '<>:"|?*' for char in value)
        or any(
            part.endswith((".", " "))
            or part.split(".", 1)[0].upper() in _WINDOWS_DEVICES
            for part in portable.parts
        )
    ):
        raise ValueError("Expected a portable relative path")
    return _inside(root, root.joinpath(*portable.parts))
