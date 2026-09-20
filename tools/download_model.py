"""Explicit, single-file model download; importing this module has no side effects.

Existing files must already match the manifest. A different file is never
overwritten; choose another destination or remove it yourself after inspection.
"""

import argparse
import hashlib
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import tomllib
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PROJECT_ROOT / "config" / "model.toml"
CHUNK_SIZE = 1024 * 1024


class ModelError(ValueError):
    """The model could not be verified or safely installed."""


def load_manifest(path=MANIFEST_PATH):
    try:
        with Path(path).open("rb") as stream:
            manifest = tomllib.load(stream)
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ModelError(f"Cannot read model manifest: {exc}") from exc
    model = manifest.get("model")
    server = manifest.get("server")
    if not isinstance(model, dict) or not isinstance(server, dict):
        raise ModelError("Model manifest requires [model] and [server]")
    patterns = {
        "repo_id": r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*",
        "revision": r"[0-9a-f]{40}",
        "filename": r"[A-Za-z0-9][A-Za-z0-9_.-]*\.gguf",
        "sha256": r"[0-9a-f]{64}",
    }
    for name, pattern in patterns.items():
        value = model.get(name)
        if not isinstance(value, str) or not re.fullmatch(pattern, value):
            raise ModelError(f"Invalid model.{name}")
    if type(model.get("size")) is not int or model["size"] <= 0:
        raise ModelError("model.size must be a positive byte count")
    required_server = {
        "host": "127.0.0.1", "port": 8080, "alias": "xiyin",
        "ctx_size": 4096, "parallel": 1, "jinja": True,
        "enable_thinking": False, "auto_mmproj": False,
    }
    for name, expected in required_server.items():
        actual = server.get(name)
        if type(actual) is not type(expected) or actual != expected:
            raise ModelError(f"Unsupported A-stage server.{name}: {actual!r}")
    return manifest


def model_destination(manifest, destination=None):
    path = Path(destination) if destination is not None else PROJECT_ROOT / "models" / manifest["model"]["filename"]
    if path.suffix.lower() != ".gguf":
        raise ModelError("Model destination must be a .gguf file path")
    # Keep the final component unresolved so a symlink cannot hide another file.
    return path.absolute()


def verify_model(path, manifest):
    path = Path(path)
    model = manifest["model"]
    if path.is_symlink() or not path.is_file():
        raise ModelError(f"Model is missing or is not a regular, non-symlink file: {path}")
    try:
        digest = hashlib.sha256()
        total = 0
        with path.open("rb") as stream:
            if os.fstat(stream.fileno()).st_size != model["size"]:
                raise ModelError(f"Model size differs from the pinned manifest: {path}")
            while chunk := stream.read(CHUNK_SIZE):
                total += len(chunk)
                digest.update(chunk)
        if total != model["size"] or digest.hexdigest() != model["sha256"]:
            raise ModelError(f"Model SHA-256 or size differs from the pinned manifest: {path}")
    except OSError as exc:
        raise ModelError(f"Cannot verify model {path}: {exc}") from exc
    return path


def _publish_without_overwrite(temporary, destination):
    # Windows rename refuses an existing destination. POSIX rename would
    # overwrite it, so link the verified inode atomically, then remove its temp
    # name. Both paths fail closed if another file appeared during the download.
    if os.name == "nt":
        os.rename(temporary, destination)
    else:
        os.link(temporary, destination)
        temporary.unlink()


def download_model(manifest, destination=None, *, opener=None):
    target = model_destination(manifest, destination)
    if os.path.lexists(target):
        verify_model(target, manifest)
        return target, "already-present"
    model = manifest["model"]
    url = ("https://huggingface.co/" + model["repo_id"] + "/resolve/"
           + model["revision"] + "/" + quote(model["filename"], safe=""))
    request = Request(url, headers={"User-Agent": "XIYIN-model-download/1", "Accept": "application/octet-stream"})
    temporary = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".part", dir=target.parent)
        temporary = Path(name)
        digest = hashlib.sha256()
        received = 0
        with os.fdopen(descriptor, "wb") as output:
            with (opener or urlopen)(request, timeout=60) as response:
                if urlparse(response.geturl()).scheme != "https":
                    raise ModelError("Model download redirected to a non-HTTPS URL")
                while chunk := response.read(CHUNK_SIZE):
                    received += len(chunk)
                    if received > model["size"]:
                        raise ModelError("Download exceeds the pinned model size")
                    digest.update(chunk)
                    output.write(chunk)
            if received != model["size"] or digest.hexdigest() != model["sha256"]:
                raise ModelError("Downloaded model does not match the pinned size and SHA-256")
            output.flush()
            os.fsync(output.fileno())
        try:
            _publish_without_overwrite(temporary, target)
        except FileExistsError:
            # A simultaneous verified download may have won publication.
            verify_model(target, manifest)
            return target, "already-present"
        return target, "downloaded"
    except (OSError, HTTPException) as exc:
        raise ModelError(f"Model download or publication failed: {exc}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Download and verify the one GGUF pinned in config/model.toml")
    parser.add_argument("--destination", type=Path, help="Explicit GGUF file path; default: project/models/<pinned filename>")
    parser.add_argument("--check", action="store_true", help="Verify an existing model only; never download or create directories")
    args = parser.parse_args(argv)
    try:
        manifest = load_manifest()
        target = model_destination(manifest, args.destination)
        if args.check:
            verify_model(target, manifest)
            status = "verified"
        else:
            target, status = download_model(manifest, target)
        print(json.dumps({"status": status, "model_path": str(target), "model": manifest["model"], "server": manifest["server"]}))
        return 0
    except (ModelError, OSError) as exc:
        print(f"Model error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
