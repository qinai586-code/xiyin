"""Non-model maintenance for one marked data root and one SQLite ledger.

Restore requires an exclusive runtime lease. All managed writers must honor
that lease; this is not protection from unrelated same-account processes.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import uuid

from .lifecycle import RuntimeLease


BACKUP_FORMAT = "xiyin.sqlite-backup.v1"
RUNTIME_API = 1


def _now():
    return datetime.now(timezone.utc).isoformat()


def _plain(path):
    path = Path(path).absolute()
    for item in (path, *path.parents):
        if os.path.lexists(item):
            if item.is_symlink() or getattr(item.lstat(), "st_file_attributes", 0) & 0x400:
                raise ValueError("Maintenance paths may not contain links or reparse points")
    return path.resolve()


def _identity(root, expected):
    root = _plain(root)
    marker = _plain(root / ".xiyin_data")
    lines = marker.read_text(encoding="utf-8").splitlines()
    if len(lines) != 2 or lines[0] != "xiyin-data-root v1" or not lines[1].startswith("id="):
        raise ValueError("Invalid existing data-root marker")
    actual = lines[1][3:]
    if not actual or actual != expected:
        raise ValueError("Data-root identity mismatch")
    return root


def _digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _write_json(path, value, *, exclusive=False):
    path = _plain(path)
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if exclusive and path.exists():
            raise FileExistsError(path)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _database_info(path):
    with closing(sqlite3.connect(Path(path).as_uri() + "?mode=ro", uri=True)) as db:
        integrity = [row[0] for row in db.execute("PRAGMA integrity_check")]
        if integrity != ["ok"]:
            raise ValueError("Backup database integrity check failed")
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"events", "memories"}.issubset(tables):
            raise ValueError("Not an XIYIN experience database")
        schema = list(db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type,name"))
        return {"user_version": db.execute("PRAGMA user_version").fetchone()[0],
                "schema_sha256": hashlib.sha256(json.dumps(schema, ensure_ascii=True).encode()).hexdigest()}


def _sqlite_backup(source, destination):
    """SQLite's backup API includes committed WAL data in one consistent image."""
    with closing(sqlite3.connect(Path(source).as_uri() + "?mode=ro", uri=True)) as src:
        with closing(sqlite3.connect(destination)) as dst:
            src.backup(dst)
            dst.execute("PRAGMA journal_mode=DELETE")
            dst.commit()
    with Path(destination).open("r+b") as stream:
        os.fsync(stream.fileno())


def validate_backup(backup_dir, expected_data_root_id):
    directory = _plain(backup_dir)
    manifest = json.loads(_plain(directory / "manifest.json").read_text(encoding="utf-8"))
    if (not isinstance(manifest, dict) or manifest.get("format") != BACKUP_FORMAT
            or type(manifest.get("runtime_api")) is not int or manifest.get("runtime_api") != RUNTIME_API
            or manifest.get("data_root_id") != expected_data_root_id
            or manifest.get("database") != "experience.sqlite3"):
        raise ValueError("Backup manifest is incompatible with this data root")
    database = _plain(directory / "experience.sqlite3")
    if database.stat().st_size != manifest.get("size_bytes") or _digest(database) != manifest.get("sha256"):
        raise ValueError("Backup size or checksum mismatch")
    if _database_info(database) != manifest.get("schema"):
        raise ValueError("Backup schema does not match its manifest")
    return manifest


def set_stop_marker(data_root, expected_id, stopped=True, reason="owner requested stop"):
    """Set or clear the control marker without opening SQLite or taking its lease.

    The CLI must authorize the current process before calling this function.
    A valid existing data identity is still required; this never initializes it.
    """
    if type(stopped) is not bool:
        raise ValueError("stopped must be a boolean")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 1000:
        raise ValueError("A short stop reason is required")
    root = _identity(data_root, expected_id)
    path = _plain(root / "supervisor.stop.json")
    record = {"id": uuid.uuid4().hex, "requested_at": _now(),
              "data_root_id": expected_id, "reason": reason.strip(), "stopped": stopped}
    if stopped:
        _write_json(path, record)
    else:
        path.unlink(missing_ok=True)
    return record


class Supervisor:
    def __init__(self, store, data_root, data_root_id, *, min_free_bytes=50 * 1024 * 1024,
                 max_backup_bytes=10 * 1024**3):
        self.root = _identity(data_root, data_root_id)
        self.data_root_id = data_root_id
        self.store = store
        if _plain(store.path) != self.root / "experience.sqlite3":
            raise ValueError("Supervisor and store must use the same data root")
        if type(min_free_bytes) is not int or min_free_bytes < 0 or type(max_backup_bytes) is not int or max_backup_bytes <= 0:
            raise ValueError("Invalid maintenance resource budget")
        self.min_free_bytes = min_free_bytes
        self.max_backup_bytes = max_backup_bytes
        self.stop_path = self.root / "supervisor.stop.json"

    def health(self):
        _identity(self.root, self.data_root_id)
        free = shutil.disk_usage(self.root).free
        return {"data_root_id": self.data_root_id, "store_open": not getattr(self.store, "_closed", False),
                "stop_requested": self.stop_requested() is not None,
                "free_bytes": free, "min_free_bytes": self.min_free_bytes,
                "resource_ready": free >= self.min_free_bytes, "model_probe": "not_performed"}

    def request_stop(self, reason="owner requested stop"):
        return set_stop_marker(self.root, self.data_root_id, reason=reason)

    def stop_requested(self):
        path = _plain(self.stop_path)
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if value.get("data_root_id") != self.data_root_id:
                raise ValueError("Stop marker belongs to another data root")
            return value
        except (ValueError, AttributeError):
            # An unreadable control marker stops work, never silently enables it.
            return {"data_root_id": self.data_root_id, "reason": "invalid stop marker", "invalid": True}

    def clear_stop(self):
        return set_stop_marker(self.root, self.data_root_id, stopped=False, reason="owner resumed work")

    def create_backup(self, backup_dir):
        _identity(self.root, self.data_root_id)
        destination = _plain(backup_dir)
        if destination.exists():
            raise FileExistsError("A backup destination must be new")
        parent = destination.parent
        if not parent.is_dir():
            raise ValueError("Backup parent directory must already exist")
        source = _plain(self.store.path)
        wal = Path(str(source) + "-wal")
        estimated = source.stat().st_size + (wal.stat().st_size if wal.exists() else 0)
        if estimated > self.max_backup_bytes or shutil.disk_usage(parent).free < estimated + self.min_free_bytes:
            raise RuntimeError("Backup resource budget is insufficient")
        destination.mkdir()
        database = destination / "experience.sqlite3"
        try:
            _sqlite_backup(source, database)
            manifest = {"format": BACKUP_FORMAT, "runtime_api": RUNTIME_API,
                        "data_root_id": self.data_root_id, "created_at": _now(),
                        "database": database.name, "size_bytes": database.stat().st_size,
                        "sha256": _digest(database), "schema": _database_info(database)}
            _write_json(destination / "manifest.json", manifest, exclusive=True)
            validate_backup(destination, self.data_root_id)
            return manifest
        except BaseException:
            # Preserve incomplete evidence; no valid manifest means no usable backup.
            (destination / "manifest.json").unlink(missing_ok=True)
            raise

    def register_release(self, manifest):
        required = {"id", "kind", "runtime_api", "artifact", "sha256"}
        if not isinstance(manifest, dict) or set(manifest) != required:
            raise ValueError("Release manifest must name only the supported fields")
        if (manifest["kind"] not in {"code", "model"} or type(manifest["runtime_api"]) is not int
                or manifest["runtime_api"] != RUNTIME_API):
            raise ValueError("Incompatible release kind or runtime API")
        if not isinstance(manifest["id"], str) or not manifest["id"] or len(manifest["id"]) > 80:
            raise ValueError("A short release id is required")
        artifact = _plain(manifest["artifact"])
        if not artifact.is_relative_to(self.root / "artifacts") or not artifact.is_file():
            raise ValueError("Releases must reference a local file under this data root's artifacts")
        if _digest(artifact) != manifest["sha256"]:
            raise ValueError("Release artifact checksum mismatch")
        value = {**manifest, "artifact": str(artifact), "registered_at": _now()}
        return self.store.write_document("releases", "release_" + manifest["id"], value, expected_version=0)

    def adopt_release(self, release_id):
        document = self.store.read_document("releases", "release_" + release_id)
        if document is None:
            raise KeyError(release_id)
        manifest = document["value"]
        artifact = _plain(manifest["artifact"])
        if (manifest["runtime_api"] != RUNTIME_API or not artifact.is_relative_to(self.root / "artifacts")
                or _digest(artifact) != manifest["sha256"]):
            raise ValueError("Registered release no longer matches its verified artifact")
        key = "active_" + manifest["kind"]
        previous = self.store.read_document("releases", key)
        value = {"release_id": release_id, "manifest": manifest,
                 "previous": {**previous["value"], "previous": None} if previous else None, "adopted_at": _now(),
                 "activation": "manifest_selection_only"}
        return self.store.write_document("releases", key, value, expected_version=previous["version"] if previous else 0)

    def rollback_release(self, kind):
        if kind not in {"code", "model"}:
            raise ValueError("Unsupported release kind")
        key = "active_" + kind
        document = self.store.read_document("releases", key)
        if document is None or not document["value"].get("previous"):
            raise ValueError("No previous selected release")
        previous = document["value"]["previous"]
        manifest = previous["manifest"]
        artifact = _plain(manifest["artifact"])
        if (manifest["kind"] != kind or manifest["runtime_api"] != RUNTIME_API
                or not artifact.is_relative_to(self.root / "artifacts")
                or _digest(artifact) != manifest["sha256"]):
            raise ValueError("Previous release artifact has changed")
        return self.store.write_document("releases", key, previous, expected_version=document["version"])


def restore_backup(backup_dir, data_root, expected_data_root_id, *, store=None):
    """Restore an explicitly confirmed backup after all managed writers stop.

    The CLI owns the one human confirmation. This function enforces identity,
    exclusive runtime ownership, closed supplied store, checksums and rollback.
    It never creates or replaces the data marker and never reopens a runtime.
    """
    root = _identity(data_root, expected_data_root_id)
    if store is not None and not getattr(store, "_closed", False):
        raise RuntimeError("Close the experience store before restoring")
    manifest = validate_backup(backup_dir, expected_data_root_id)
    target = _plain(root / "experience.sqlite3")
    if not target.is_file():
        raise FileNotFoundError("Restore requires an existing experience database")
    lease = RuntimeLease(_plain(root / "runtime.lock"))
    staging = root / ("restore-stage-" + uuid.uuid4().hex + ".sqlite3")
    rollback = root / ("restore-rollback-" + uuid.uuid4().hex + ".sqlite3")
    replaced = False
    try:
        if _database_info(target) != manifest["schema"]:
            raise ValueError("Backup schema requires an explicit migration before restore")
        # Checkpoint and release our own connection before replacing a database.
        with closing(sqlite3.connect(target, timeout=0.1)) as current:
            current.execute("PRAGMA locking_mode=EXCLUSIVE")
            current.execute("BEGIN EXCLUSIVE")
            current.commit()
            checkpoint = current.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if checkpoint and checkpoint[0] != 0:
                raise RuntimeError("Database still has active readers or writers")
        _sqlite_backup(target, rollback)
        _sqlite_backup(_plain(Path(backup_dir) / "experience.sqlite3"), staging)
        if _database_info(staging) != manifest["schema"]:
            raise ValueError("Staged restore schema mismatch")
        _identity(root, expected_data_root_id)
        # No managed connection remains. Remove empty checkpoint sidecars only.
        for suffix in ("-wal", "-shm"):
            sidecar = _plain(Path(str(target) + suffix))
            if sidecar.exists():
                if suffix == "-wal" and sidecar.stat().st_size:
                    raise RuntimeError("Uncheckpointed WAL appeared during restore")
                sidecar.unlink()
        os.replace(staging, target)
        replaced = True
        if _database_info(target) != manifest["schema"]:
            raise ValueError("Restored database failed verification")
        _identity(root, expected_data_root_id)
        return {"restored": True, "data_root_id": expected_data_root_id,
                "backup": str(_plain(backup_dir)), "rollback_database": str(rollback), "manifest": manifest}
    except BaseException:
        if replaced:
            os.replace(rollback, target)
        raise
    finally:
        staging.unlink(missing_ok=True)
        lease.close()
