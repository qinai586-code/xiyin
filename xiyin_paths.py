"""Resolve code and persistent-data paths without creating or migrating data.

The markers locate roots; they do not grant permission. Link containment is a
path check, not a sandbox or protection against concurrent filesystem changes.
"""

import os
from pathlib import Path, PureWindowsPath
import re
import tomllib


ROOT_MARKER = ".xiyin_root"
CONFIG_REL = ("config", "paths.toml")
DATA_MARKER = ".xiyin_data"
DATA_MARKER_HEADER = "xiyin-data-root v1"
DATA_ENV = "XIYIN_DATA_ROOT"
_COMPONENT = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*")
_WINDOWS_DEVICES = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {
    prefix + suffix
    for prefix in ("COM", "LPT")
    for suffix in "123456789¹²³"
}


class XiyinPathError(ValueError):
    """An explicit path failure; ValueError preserves existing _inside callers."""


def _resolved(path: Path, *, strict: bool = False) -> Path:
    try:
        return Path(path).resolve(strict=strict)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise XiyinPathError(f"Cannot resolve path {path!s}: {exc}") from exc


def _inside(root: Path, path: Path) -> Path:
    """Resolve a path and retain the existing containment-checking API."""
    root = _resolved(root)
    resolved = _resolved(path)
    if not resolved.is_relative_to(root):
        raise XiyinPathError(f"Path escapes root {root}: {path}")
    return resolved


def project_root() -> Path:
    """Find this resolver's own code root, independently of the working directory."""
    root = _resolved(Path(__file__)).parent
    for parts in ((ROOT_MARKER,), CONFIG_REL):
        path = _inside(root, root.joinpath(*parts))
        if not path.is_file():
            raise XiyinPathError(f"Missing {'/'.join(parts)} in code root {root}")
    return root


def _parts(value: str) -> tuple[str, ...]:
    # Validate before Path normalizes away empty or dot components. The ASCII
    # allowlist applies only to relative entries, never to the absolute roots.
    if not isinstance(value, str) or not value:
        raise XiyinPathError("Expected a nonempty portable relative path")
    parts = value.split("/")
    for part in parts:
        if (not _COMPONENT.fullmatch(part) or part.endswith(".")
                or part.split(".", 1)[0].upper() in _WINDOWS_DEVICES):
            raise XiyinPathError(f"Illegal relative path component: {part!r}")
    return tuple(parts)


def under(base: Path, rel: str) -> Path:
    """Join a portable relative path under an existing base, following links."""
    parts = _parts(rel)
    root = _resolved(base, strict=True)
    if not root.is_dir():
        raise XiyinPathError(f"Base is not a directory: {root}")
    return _inside(root, root.joinpath(*parts))


def resolve_path(name: str) -> Path:
    """Resolve one [paths] entry under the code root, without creating it."""
    root = project_root()
    config = _inside(root, root.joinpath(*CONFIG_REL))
    try:
        with config.open("rb") as stream:
            table = tomllib.load(stream).get("paths")
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise XiyinPathError(f"Cannot read config/paths.toml: {exc}") from exc
    if not isinstance(table, dict):
        raise XiyinPathError("config/paths.toml has no [paths] table")
    if not isinstance(name, str) or name not in table:
        raise XiyinPathError(f"Unknown path name: {name!r}")
    return under(root, table[name])


def _absolute_data_path(raw: str) -> Path:
    """Check a native local absolute path, allowing Unicode and internal spaces."""
    windows = PureWindowsPath(raw)
    path = Path(raw)
    if (not raw or not path.is_absolute() or raw.startswith(("\\\\", "//"))
            or windows.drive.startswith("\\")):
        raise XiyinPathError(f"{DATA_ENV} must be an absolute local path")
    for part in path.parts[1:]:
        if part in (".", ".."):
            continue
        if (part.endswith((".", " "))
                or part.split(".", 1)[0].upper() in _WINDOWS_DEVICES
                or any(ord(char) < 32 or char in '<>:"|?*\\' for char in part)):
            raise XiyinPathError(f"{DATA_ENV} has an invalid path component: {part!r}")
    root = _resolved(path, strict=True)
    if str(root).startswith(("\\\\", "//")):
        raise XiyinPathError(f"{DATA_ENV} resolves to a non-local path")
    return root


def _marker_id(root: Path) -> str:
    marker = _inside(root, root / DATA_MARKER)
    if not marker.is_file():
        raise XiyinPathError(f"Data root has no {DATA_MARKER}: {root}")
    try:
        lines = marker.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise XiyinPathError(f"Cannot read {DATA_MARKER}: {exc}") from exc
    fields = [line for line in lines[1:] if line]
    if (not lines or lines[0] != DATA_MARKER_HEADER or len(fields) != 1
            or not fields[0].startswith("id=")):
        raise XiyinPathError(f"Invalid {DATA_MARKER} format")
    identity = fields[0][3:].strip()
    if not identity or any(ord(char) < 32 or ord(char) == 127 for char in identity):
        raise XiyinPathError(f"{DATA_MARKER} requires a nonempty, printable id")
    return identity


def _data_root_info() -> tuple[Path, str]:
    # Presence, including an explicitly empty override, wins over configuration.
    # No branch creates, repairs, or silently falls back to another data root.
    project_root()
    if DATA_ENV in os.environ:
        root = _absolute_data_path(os.environ[DATA_ENV])
    else:
        root = resolve_path("data")
    if not root.is_dir():
        raise XiyinPathError(f"Data root is not an existing directory: {root}")
    return root, _marker_id(root)


def data_root() -> Path:
    """Return an existing, marked data root; XIYIN_DATA_ROOT takes precedence."""
    return _data_root_info()[0]


def data_root_id() -> str:
    """Return the validated data marker identity for startup and evidence logs."""
    return _data_root_info()[1]
