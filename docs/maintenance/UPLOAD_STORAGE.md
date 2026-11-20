# Worktree-independent upload storage (v0.9.1)

## Problem

Raw uploaded files (kept for provenance only; D106) were stored under `UPLOAD_DIR`, which defaulted to
`<checkout>/var/uploads`, and a relative `UPLOAD_DIR` also resolved against the running checkout. With several Git
worktrees, each API process used a different directory:

- a dataset stored while the API ran from one checkout was invisible to an API started from another;
- deleting the incident from the other checkout removed its records but silently left the raw files behind, because
  deletion only touched directories under the *current* root.

Investigations and the UI never read these files. They use the normalized records in `ops.uploaded_datasets`, so
analysis was not affected.

## Fix

- `UPLOAD_DIR` defaults to an absolute directory **outside every checkout**: `$XDG_DATA_HOME/opspilot/uploads`, else
  `~/.local/share/opspilot/uploads`. Every worktree resolves the same place.
  - An explicit absolute or `~` path is used as is.
  - An empty value means the default.
  - A relative value keeps its old repo-relative meaning for compatibility, but is not recommended.
- One resolver, `opspilot_api.services.upload_storage.UploadStorage`, is used to store, locate and delete. A
  dataset's directory is always `<UPLOAD_DIR>/<dataset UUID>`:
  - the UUID is validated;
  - the directory must sit directly under the resolved root and must not be a symbolic link;
  - file names are single components (no traversal).
- Deletion removes `<UPLOAD_DIR>/<dataset UUID>`, whichever checkout stored it. It never deletes anything outside
  `UPLOAD_DIR`. If the dataset row records an older location (`storage_dir`) that still exists, the result reports it
  as `legacy_files_kept`.
- Existing rows are not changed. `storage_dir` stays as recorded and is treated as a legacy location.

The isolated E2E stack keeps its own `E2E_UPLOAD_DIR` (default `<checkout>/var/e2e-uploads`), so test uploads never
mix with development data.

## Migrating existing files

```bash
# 1. back up the originals (outside any checkout)
mkdir -p ~/OpsPilotBackups/$(date +%F)-upload-storage
tar -C <old checkout> -czf ~/OpsPilotBackups/$(date +%F)-upload-storage/var-uploads.tar.gz var/uploads

# 2. see what would be copied (reads the database only; the API may keep running)
uv run opspilot uploads migrate-storage

# 3. copy, verified by SHA-256
uv run opspilot uploads migrate-storage --apply

# 4. confirm every upload is present in UPLOAD_DIR
uv run opspilot uploads list
```

`migrate-storage` handles each uploaded dataset as follows:

1. Validates the recorded directory: it must be named after the dataset and contain only regular files.
2. Copies it into a staging directory inside `UPLOAD_DIR`.
3. Verifies the SHA-256 checksum of every file.
4. Renames the staging directory to `<UPLOAD_DIR>/<dataset UUID>` (atomic).

It never deletes or modifies the originals, and never changes database rows.

Result statuses:

| Status | Meaning |
|---|---|
| `would_copy` | dry run: the dataset would be copied |
| `copied` | copied and verified |
| `already_copied` | an identical copy is already in `UPLOAD_DIR` |
| `in_root` | the recorded location is already the shared one |
| `conflict` | a different copy exists in `UPLOAD_DIR`; left alone, resolve by hand |
| `source_missing` | the recorded directory no longer exists |
| `refused` | the recorded directory is not a plain dataset directory |
| `no_files` | no raw files were recorded |

After a successful migration, delete the old `<checkout>/var/uploads/<dataset UUID>` copies yourself once you no
longer need them. OpsPilot never deletes outside `UPLOAD_DIR`.

The new default takes effect for an API process running code that includes this change. Restart it with `make stop
&& make dev` from that checkout.
