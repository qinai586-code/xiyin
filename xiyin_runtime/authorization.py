"""Validate the configured Windows runtime without a fixed local account."""

import os
from pathlib import Path
import shutil

import xiyin_identity
import xiyin_paths


class AuthorizationError(RuntimeError):
    pass


def authorize_runtime() -> None:
    if os.name != "nt":
        raise AuthorizationError("Live runtime requires Windows; offline tests and doctor remain available")
    try:
        root = xiyin_paths.project_root()
        policy = xiyin_identity.load_policy(root)
        role, _ = xiyin_identity.current_role(policy)
        if role != "runtime":
            raise AuthorizationError("Current Windows token is not a permitted runtime identity")
        xiyin_identity.validate_runtime_cwd(policy, Path.cwd())
        if shutil.disk_usage(root).free < 1024 * 1024 * 1024:
            raise AuthorizationError("Runtime volume has less than 1 GiB free")
    except AuthorizationError:
        raise
    except Exception as exc:
        raise AuthorizationError(f"Windows runtime identity check failed: {exc}") from exc
