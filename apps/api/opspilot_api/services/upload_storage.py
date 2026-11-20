"""Where raw uploaded files live, resolved the same way by every writer, reader and deleter (v0.9.1).

Raw copies of uploaded files are kept for provenance only (D106); investigations read the normalized records in the
database, never these files. The directory of a dataset is always ``<UPLOAD_DIR>/<dataset UUID>``:

- the UUID is validated (server-generated, never user input), so no path component comes from a request;
- the directory must sit directly under the resolved root and must not be a symbolic link;
- file names inside it are validated the same way (one component, no traversal).

``storage_dir`` recorded on old dataset rows may point at another checkout's ``var/uploads`` (before the root became
worktree-independent). It is treated as a *legacy* location: it is reported, and ``migrate`` can copy it into the
root (verified by SHA-256), but nothing outside the root is ever deleted or modified, and database rows are not changed.
"""

from __future__ import annotations

import hashlib
import shutil
import uuid
from pathlib import Path
from typing import Any

from opspilot_shared.logging import get_logger

_log = get_logger(__name__)


class StorageError(ValueError):
    """A path that is not a valid dataset location under the configured root."""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _manifest(directory: Path) -> dict[str, str]:
    """{file name: sha256} for a dataset directory: regular files only, no subdirectories, no links."""
    out: dict[str, str] = {}
    for entry in sorted(directory.iterdir()):
        if entry.is_symlink() or not entry.is_file():
            raise StorageError(f"unexpected entry {entry.name!r} in {directory} (only regular files are expected)")
        out[entry.name] = _sha256(entry)
    return out


class UploadStorage:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).expanduser().resolve()

    # -- resolution -------------------------------------------------------------------------------------------------
    def dataset_dir(self, dataset_id: uuid.UUID | str) -> Path:
        """``<root>/<uuid>``; raises ``StorageError`` for anything that is not a UUID or would leave the root."""
        try:
            did = uuid.UUID(str(dataset_id))
        except ValueError as exc:
            raise StorageError("dataset id is not a UUID") from exc
        path = self.root / str(did)
        if path.is_symlink() or path.resolve().parent != self.root:
            raise StorageError("dataset directory is outside the upload root")
        return path

    def file_path(self, directory: Path, name: str) -> Path:
        path = directory / name
        if (
            not name
            or "/" in name
            or "\\" in name
            or name in (".", "..")
            or path.resolve().parent != directory.resolve()
        ):
            raise StorageError("invalid file name")
        return path

    def create(self, dataset_id: uuid.UUID) -> Path:
        """Create the (new, empty) directory of a dataset, mode 0700; the root is created 0700 if missing."""
        self.root.mkdir(parents=True, mode=0o700, exist_ok=True)
        target = self.dataset_dir(dataset_id)
        target.mkdir(mode=0o700, exist_ok=False)
        return target

    def remove(self, dataset_id: uuid.UUID | str) -> bool:
        """Delete the dataset's directory under the root. Nothing outside the root is ever removed."""
        try:
            path = self.dataset_dir(dataset_id)
        except StorageError:
            return False
        if not path.is_dir():
            return False
        shutil.rmtree(path)
        return True

    def locate(self, dataset_id: uuid.UUID | str, recorded: str | None) -> dict[str, Any]:
        """Where a dataset's raw files are: the root location, and a legacy recorded location if it differs."""
        path = self.dataset_dir(dataset_id)
        out: dict[str, Any] = {"path": str(path), "present": path.is_dir()}
        legacy = Path(recorded).expanduser() if recorded else None
        if legacy is not None and legacy.resolve() != path.resolve():
            out["legacy_path"] = str(legacy)
            out["legacy_present"] = legacy.is_dir() and not legacy.is_symlink()
        return out

    # -- migration --------------------------------------------------------------------------------------------------
    def migrate(self, dataset_id: uuid.UUID | str, recorded: str | None, *, apply: bool) -> dict[str, Any]:
        """Copy a legacy dataset directory into the root, verified by SHA-256. Never deletes or modifies the source.

        Statuses: ``in_root`` (nothing to do), ``no_files`` (nothing recorded), ``source_missing``, ``would_copy``
        (dry run), ``copied``, ``already_copied`` (identical copy present), ``conflict`` (a different copy is present:
        left alone), ``refused`` (the source is not a plain dataset directory)."""
        target = self.dataset_dir(dataset_id)
        report: dict[str, Any] = {"dataset_id": str(dataset_id), "target": str(target), "source": recorded}
        if not recorded:
            return {**report, "status": "no_files"}
        source = Path(recorded).expanduser()
        if source.resolve() == target.resolve():
            return {**report, "status": "in_root"}
        if source.is_symlink() or not source.is_dir():
            return {**report, "status": "source_missing" if not source.exists() else "refused"}
        if source.name != str(uuid.UUID(str(dataset_id))):
            return {**report, "status": "refused", "reason": "the recorded directory is not named after the dataset"}
        try:
            expected = _manifest(source)
        except StorageError as exc:
            return {**report, "status": "refused", "reason": str(exc)}
        report["files"] = expected
        if target.exists():
            try:
                present = _manifest(target)
            except StorageError as exc:
                return {**report, "status": "conflict", "reason": str(exc)}
            return {**report, "status": "already_copied" if present == expected else "conflict"}
        if not apply:
            return {**report, "status": "would_copy"}
        self.root.mkdir(parents=True, mode=0o700, exist_ok=True)
        staging = self.root / f".{target.name}.partial-{uuid.uuid4().hex[:8]}"
        staging.mkdir(mode=0o700)
        try:
            for name in expected:
                dest = self.file_path(staging, name)
                shutil.copyfile(source / name, dest)
                dest.chmod(0o600)
            copied = _manifest(staging)
            if copied != expected:
                raise StorageError("checksum mismatch after copy")
            staging.rename(target)  # atomic within the root: the dataset directory appears complete or not at all
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        _log.info("upload_storage_migrated", dataset_id=str(dataset_id), files=len(expected))
        return {**report, "status": "copied", "verified": True}
