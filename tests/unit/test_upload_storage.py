"""v0.9.1: worktree-independent upload storage — one resolved root, no path escapes, verified migration."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from opspilot_api.services.upload_storage import StorageError, UploadStorage
from opspilot_shared.config import REPO_ROOT, Settings, default_upload_dir


# ---------------------------------------------------------------------------------------------- configuration
def test_default_root_is_shared_and_outside_every_checkout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("UPLOAD_DIR", raising=False)
    root = Settings(_env_file=None).upload_dir  # type: ignore[call-arg]
    assert root == Path.home() / ".local/share/opspilot/uploads" and root.is_absolute()
    assert REPO_ROOT not in root.parents  # not inside this (or any) checkout
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert default_upload_dir() == tmp_path / "opspilot/uploads"
    monkeypatch.setenv("XDG_DATA_HOME", "relative/dir")  # ignored, as the XDG spec requires
    assert default_upload_dir() == Path.home() / ".local/share/opspilot/uploads"


def test_explicit_values(tmp_path: Path) -> None:
    s = lambda v: Settings(_env_file=None, upload_dir=v).upload_dir  # type: ignore[call-arg]  # noqa: E731
    assert s(str(tmp_path)) == tmp_path  # absolute: as is
    assert s("~/opspilot-data/uploads") == Path.home() / "opspilot-data/uploads"
    assert s("") == default_upload_dir()  # UPLOAD_DIR= means the default, never the current directory
    assert s("var/uploads") == REPO_ROOT / "var/uploads"  # relative: unchanged v0.5 meaning (compatibility)


def test_two_checkouts_resolve_the_same_directory(tmp_path: Path) -> None:
    """Two API processes started from different worktrees share one root, so either can find and delete a
    dataset the other stored (the v0.9.0 local-sync finding)."""
    root = tmp_path / "shared"
    a, b = UploadStorage(root), UploadStorage(str(root) + "/")
    did = uuid.uuid4()
    stored = a.create(did)
    (stored / "01-app.log").write_text("x")
    assert b.dataset_dir(did) == stored and b.locate(did, str(stored)) == {"path": str(stored), "present": True}
    assert b.remove(did) and not stored.exists()


# ---------------------------------------------------------------------------------------------- containment
@pytest.mark.parametrize("bad", ["../etc", "..", "/etc/passwd", "a/b", "", "not-a-uuid", "00000000-0000-0000-0000"])
def test_dataset_ids_must_be_uuids(tmp_path: Path, bad: str) -> None:
    with pytest.raises(StorageError):
        UploadStorage(tmp_path).dataset_dir(bad)
    assert UploadStorage(tmp_path).remove(bad) is False


@pytest.mark.parametrize("name", ["../x", "a/b", "..", ".", "", "..\\x"])
def test_file_names_cannot_leave_the_dataset_directory(tmp_path: Path, name: str) -> None:
    st = UploadStorage(tmp_path)
    d = st.create(uuid.uuid4())
    with pytest.raises(StorageError):
        st.file_path(d, name)


def test_symlinked_dataset_directory_is_never_followed(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("precious")
    st = UploadStorage(tmp_path / "root")
    st.root.mkdir()
    did = uuid.uuid4()
    (st.root / str(did)).symlink_to(outside, target_is_directory=True)
    with pytest.raises(StorageError):
        st.dataset_dir(did)
    assert st.remove(did) is False and (outside / "keep.txt").read_text() == "precious"


# --------------------------------------------------------------------------------------------- cleanup / missing
def test_remove_deletes_only_the_root_copy_and_tolerates_missing_files(tmp_path: Path) -> None:
    st = UploadStorage(tmp_path / "root")
    legacy = tmp_path / "old-checkout/var/uploads"
    did = uuid.uuid4()
    (legacy / str(did)).mkdir(parents=True)
    (legacy / str(did) / "01-a.log").write_text("legacy")
    assert st.remove(did) is False  # nothing in the root: missing files are not an error
    st.create(did)
    assert st.remove(did) is True and not (st.root / str(did)).exists()
    assert (legacy / str(did) / "01-a.log").read_text() == "legacy"  # outside the root: never deleted
    info = st.locate(did, str(legacy / str(did)))
    assert info["present"] is False and info["legacy_present"] is True


# --------------------------------------------------------------------------------------------- migration
def _legacy(tmp_path: Path, did: uuid.UUID, files: dict[str, str]) -> Path:
    d = tmp_path / "primary-checkout/var/uploads" / str(did)
    d.mkdir(parents=True)
    for name, text in files.items():
        (d / name).write_text(text)
    return d


def test_migration_is_dry_run_by_default_then_copies_verified_and_keeps_originals(tmp_path: Path) -> None:
    st = UploadStorage(tmp_path / "shared")
    did = uuid.uuid4()
    src = _legacy(tmp_path, did, {"01-app.log": "line 1\n", "02-metrics.csv": "ts,value\n"})
    dry = st.migrate(did, str(src), apply=False)
    assert (
        dry["status"] == "would_copy" and not st.root.exists() and set(dry["files"]) == {"01-app.log", "02-metrics.csv"}
    )
    done = st.migrate(did, str(src), apply=True)
    target = st.root / str(did)
    assert done["status"] == "copied" and done["verified"] is True
    assert (target / "01-app.log").read_text() == "line 1\n"
    assert (
        oct(target.stat().st_mode & 0o777) == "0o700" and oct((target / "01-app.log").stat().st_mode & 0o777) == "0o600"
    )
    assert (src / "01-app.log").read_text() == "line 1\n"  # the original is untouched
    assert not [p for p in st.root.iterdir() if p.name.startswith(".")]  # no staging directory left behind
    assert st.migrate(did, str(src), apply=True)["status"] == "already_copied"  # idempotent


def test_migration_conflicts_and_refusals(tmp_path: Path) -> None:
    st = UploadStorage(tmp_path / "shared")
    did = uuid.uuid4()
    src = _legacy(tmp_path, did, {"01-app.log": "original"})
    st.create(did)
    (st.root / str(did) / "01-app.log").write_text("different")
    conflict = st.migrate(did, str(src), apply=True)
    assert conflict["status"] == "conflict" and (st.root / str(did) / "01-app.log").read_text() == "different"

    other = uuid.uuid4()
    assert st.migrate(other, None, apply=True)["status"] == "no_files"
    assert st.migrate(other, str(tmp_path / "gone" / str(other)), apply=True)["status"] == "source_missing"
    misnamed = _legacy(tmp_path, uuid.uuid4(), {"x.log": "x"})
    assert st.migrate(other, str(misnamed), apply=True)["status"] == "refused"  # not named after the dataset
    nested = _legacy(tmp_path, other, {"a.log": "a"})
    (nested / "sub").mkdir()
    assert st.migrate(other, str(nested), apply=True)["status"] == "refused"  # unexpected structure
    third = uuid.uuid4()
    linked = _legacy(tmp_path, third, {"a.log": "a"})
    (linked / "evil.log").symlink_to(tmp_path / "primary-checkout")
    assert st.migrate(third, str(linked), apply=True)["status"] == "refused"  # never follows links
    assert not (st.root / str(other)).exists() and not (st.root / str(third)).exists()


def test_failed_copy_leaves_no_partial_dataset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import opspilot_api.services.upload_storage as mod

    st = UploadStorage(tmp_path / "shared")
    did = uuid.uuid4()
    src = _legacy(tmp_path, did, {"01-app.log": "data"})
    real = mod._manifest
    calls = {"n": 0}

    def tampered(directory: Path) -> dict[str, str]:
        calls["n"] += 1
        out = real(directory)
        return {k: "0" * 64 for k in out} if calls["n"] == 2 else out  # the copy's checksums do not match

    monkeypatch.setattr(mod, "_manifest", tampered)
    with pytest.raises(StorageError, match="checksum"):
        st.migrate(did, str(src), apply=True)
    assert not (st.root / str(did)).exists() and list(st.root.iterdir()) == []
    assert (src / "01-app.log").read_text() == "data"
