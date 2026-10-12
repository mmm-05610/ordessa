# ordessa_infrastructure.filesystem

Implementation: `__init__.py`, `directories.py`, `files.py`, `publication.py`,
`errors.py` in this directory.

## Public entry

* `directories` — `open_directory_relative` (child of a trusted fd),
  `open_directory_absolute` (component-by-component from `/`),
  `open_directory_nofollow` (refuses a symlink and a changed device/inode),
  `is_safe_component`.
* `files` — `open_file_at`, `open_regular_at`, `read_regular_at`,
  `create_exclusive_at`, `sync_directory`.
* `publication` — `publish_file` with `PublicationStage` / `PublishedFile`.
* `errors` — `UnsafePathError`, `UnsafeFileTypeError`, `DirectoryReplacedError`,
  `PlatformUnsupportedError`, `FileAlreadyExistsError`, `PublicationError`.

## Guarantees and ownership

* Absolute paths, empty names, `.`/`..`, NUL and separator-bearing names are
  refused. Every open is relative to a trusted directory fd with `O_NOFOLLOW`.
* Where the platform lacks `O_NOFOLLOW`/`O_DIRECTORY` the call raises
  `PlatformUnsupportedError`; it never substitutes `0` and pretends the
  guarantee held.
* A borrowed directory/root fd is never closed. Each newly opened fd is owned by
  the caller; if an internal step fails the new fd is closed first.
* Permission bits are always passed by the caller; no single business mode is
  forced.
* The trusted directory fd is a genuine premise, not a guarantee this package
  establishes: it does not defend against a concurrent same-directory actor
  changing entries between a check and an operation.

## Publication stages

`publish_file` validates `target_name` and `temp_name` (distinct safe
components: no absolute paths, `..`, separators or NUL) **before any IO**, then
runs `write` → `file_fsync` → `replace` → `directory_fsync`. The target is
replaced atomically; there is no "do not overwrite" mode — a caller needing
no-clobber must prove absence itself, and the primitive does not pretend to
offer a race-free no-clobber it cannot guarantee. Before replacement, failure leaves the target untouched and closes the owned
file descriptor. It deliberately does **not** look up, unlink or rename the
remaining temporary name: `stat` followed by `unlink` cannot atomically exclude
another actor replacing that name. A temporary may remain complete, partial or
empty. The caller knows `temp_name` and owns cleanup under conditions that
exclude concurrent namespace replacement. There is no implicit retry; an
occupied temporary name causes the next exclusive create to refuse, preserving
its bytes. Pre-existing names and other actors' replacement files are retained.
On success the normal atomic rename consumes the temporary name. Once
the replace succeeds the target has *already changed*; if the directory `fsync`
then fails, `PublicationError(stage='directory_fsync',
target_may_have_changed=True)` is raised and the mechanism does **not** roll
back or delete the final file — persistence is unknown and that is stated, not
hidden. A zero-byte `os.write` raises instead of spinning.

`read_regular_at(limit=…)` enforces the bound on the opened size *and* on the
bytes actually read, so a file that grows after the open cannot exceed it.
Opens add `O_NONBLOCK` so a FIFO/device is rejected by the post-open type check
instead of blocking forever.

## What stays with the owners

Complete-directory publication, business validation, identity-change cleanup,
`wal`/`shm` cleanup and record-format-specific commits (Decision evidence
`terminal.commit`, kernel `storage/objects.py`/`secrets.py`, Agent private
generation leases) remain with their owners. This module is a single-file
primitive, not a publication authority.

## Consumer wired this round

`packages/engineering/src/ordessa_engineering/adapters/filesystem/package_writer.py`
uses the directory open and exclusive-create primitives, mapping neutral errors
to its own `EngineeringError` codes and keeping its per-file → directory →
parent `fsync` order and its directory-publication policy. It is a pinned source
file, so its `operation_registry.v1.json` hash was synced for exactly that file.

## Publication cleanup repair and guarantee boundary

Failure-time `stat`/`unlink` cleanup has been removed. The former controlled
counterexample replaced the temporary between those operations and caused the
replacement to be deleted; its original failed log is retained in
`docs/implementation/nightly/evidence/infrastructure-20261011-validation/publication-race-probe.log`.
The formal regression now proves that the lookup/deletion scheduling point is
unreachable, and additional write/fsync/replace failures retain actual replacement
files, close the owned fd, and leave the final target intact.

This repairs destructive failure cleanup by accepting explicit residue. It does
not promise automatic safe reclamation under arbitrary concurrent mutation.
The owning caller must establish namespace control before cleaning that residue;
there is no inode compare-and-unlink facility here. No automatic best-effort
cleanup or hidden fallback remains.

Success uses pathname `rename`, so callers must control the temporary name until
replacement completes. The primitive does not fence a concurrent actor swapping
that source name, nor attest the renamed inode against the write fd. Atomic
replacement and post-replace unknown durability remain the original semantics;
this repair does not change them. The same trusted-directory/namespace premise
applies to final-target claims before replacement.
