"""Reuse the registered Windows runtime identity without changing its policy."""

import os
from pathlib import Path
import shutil

import xiyin_identity
import xiyin_paths


class AuthorizationError(RuntimeError):
    pass


def authorize_runtime() -> None:
    if os.name != "nt":
        raise AuthorizationError("Live runtime requires the registered Windows machine; offline tests and doctor remain available")
    try:
        root = xiyin_paths.project_root()
        policy = xiyin_identity.load_policy(root)
        role, _ = xiyin_identity.current_role(policy)
        if role != "runtime":
            raise AuthorizationError("Current Windows token is not a registered runtime identity")
        cwd = Path.cwd().resolve()
        if not any(cwd.is_relative_to(Path(p).resolve()) for p in policy["allowed_cwd_roots"]):
            raise AuthorizationError("Working directory is outside the registered runtime locations")
        if shutil.disk_usage(root).free < 1024 * 1024 * 1024:
            raise AuthorizationError("Runtime volume has less than 1 GiB free")
    except AuthorizationError:
        raise
    except Exception as exc:
        raise AuthorizationError(f"Windows runtime identity check failed: {exc}") from exc
