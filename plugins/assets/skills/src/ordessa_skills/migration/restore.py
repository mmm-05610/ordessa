"""Backup / restore of the Skills-owned slice of a data root (tasks.md T16
「最小数据恢复演示」; verification.md G08/G22 「数据备份恢复一致」;
plan.md 原有 Assets-Skill 迁移: 若需要修改真实用户数据，另给备份/恢复和用户确认).

What this module IS: the backup/restore half of the evidence the migration
story was missing. profile_bindings ships plan/apply/verify/rollback — that
proves the domain tables can be reverted *logically*. This file proves a
damaged **data root** can be restored *byte-wise from a copy*, at the level
the design asks for: synthetic roots, honest coverage boundaries, typed
refusals — not a claim about real user data.

Coverage — what a snapshot copies, records and what restore replaces
--------------------------------------------------------------------
Copied (restorable):

* the product SQLite file ``state/agentbox.sqlite`` plus its ``-wal`` /
  ``-shm`` sidecars when present. The data root must be at rest (a
  non-empty sidecar refuses the snapshot with a type): this is a
  quiescent-copy tool, not a hot-backup / WAL-safe one.
* every file under ``assets/skill/**`` — the immutable
  ``skill/<assetId>/<revision>`` trees — copied into the backup, each with
  its per-file sha256, plus the ``sha256:`` tree digest of every revision
  directory (re-derived through
  :func:`pacthold_runtime_compat.resource_contracts.runtime_artifacts.runtime_artifact_tree_digest`,
  the same spelling the revision store installs with; G01: 拼写不静默改变).

Recorded-and-verified only (NOT copied, NOT restored): every other byte
under ``assets/`` (mcp/, plugin/, catalogs/, the approvals sidecar files —
anything outside ``skill/``). Chosen smaller implementation and why: a
Skills backup that copied foreign bytes would become the de-facto owner of
*other* businesses' data — plan.md 原有 Assets-Skill 迁移 gives those kinds
to their old owners (旧表其他 kind 由迁移账指定旧业务所有者), so restoring
them from here would usurp that ownership even when the copy is on disk.
Recording instead lets :func:`restore` *prove* the foreign bytes are exactly
what the snapshot saw (or refuse, see below) — which is precisely G01's
counter-example 「非 Skill 行被修改」 turned into evidence, at a smaller
implementation cost.

Deliberately NOT covered (state these limits when quoting this demo):

* ``state/`` files other than the database (objects, secrets stores) — not
  this domain's data, not copied, not verified.
* Row-granular database restore: the SQLite file is one blob; restoring it
  reverts *everything inside it*, foreign-kind rows included. The demo
  pins that foreign rows are byte-identical after restore because the
  simulated damage never edited them *in the database* — a real foreign DB
  edit would be reverted too, and the report says so honestly.
* live/hot roots, cross-machine restore, encryption, compression — none.
* real user data: :func:`snapshot` and :func:`restore` refuse any root that
  does not resolve strictly under ``tempfile.gettempdir()`` unless the
  caller asserts ``allow_user_data=True`` — the same path-shape probe as
  profile_bindings' guard, with the same honest wording (see
  :func:`_require_synthetic_path`).

Refusals (codes registered here, once — ``RestoreError``):
``RESTORE_DATA_ROOT_INVALID``, ``RESTORE_BACKUP_INSIDE_ROOT``,
``RESTORE_BACKUP_INSIDE_REPO``, ``RESTORE_USER_DATA_CONFIRMATION_REQUIRED``,
``RESTORE_ENTRY_INVALID``, ``RESTORE_BACKUP_INVALID``,
``RESTORE_MANIFEST_MISMATCH``, ``RESTORE_FOREIGN_ROOT``,
``RESTORE_FOREIGN_DRIFT``.

Safety invariants: the backup never lands inside the data root or inside
this repository (AGENTS.md rule 7 — no user data, and no run data, in the
repo); snapshot is all-or-nothing (a refusal leaves no partial backup);
restore writes NOTHING before its full pre-flight (foreign-byte comparison,
destination identity) has passed; no symlink is ever followed in either
direction (an encountered symlink or special file is a typed refusal, not a
copy — the tree-digest walker's fail-closed rule, reused here); nothing
here deletes a data root or a backup, and nothing touches ``git``.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from pacthold_runtime_compat.resource_contracts.runtime_artifacts import (
    runtime_artifact_tree_digest,
)

from ..api.errors import AssetDomainError

#: Manifest schema id — bump deliberately, never silently (G01 拼写规则).
MANIFEST_VERSION = "ordessa-skills-restore-v1"

#: The product SQLite file, exactly where ``Database`` puts it
#: (plugins/runtime-compat storage/database.py: data_root/"state"/
#: "agentbox.sqlite"), plus its optional WAL sidecars.
DB_RELATIVE = ("state", "agentbox.sqlite")
DB_SIDECAR_SUFFIXES = ("-wal", "-shm")

ASSETS_RELATIVE = "assets"
SKILL_RELATIVE = "assets/skill"

BACKUP_DIR_PREFIX = "skill-restore-"


class RestoreError(AssetDomainError):
    """One backup/restore operation was refused; see the module docstring
    for the code registry."""


# -- paths and guards ---------------------------------------------------------


def _repo_root() -> Path | None:
    """The monorepo root when this module is imported from inside a real
    checkout (marker: AGENTS.md next to ``docs``). When shipped as an
    installed wheel the guess is empty and the repo guard is skipped —
    the in-root guard still stands; this limit is stated, not hidden."""
    guess = Path(__file__).resolve().parents[6]
    return guess if (guess / "AGENTS.md").is_file() else None


def _is_synthetic_path(path: Path) -> bool:
    """True only when ``path`` resolves STRICTLY under
    ``tempfile.gettempdir()`` (the temp dir itself is not synthetic). This
    is a path-shape probe, nothing more: it reads no backup evidence and
    cannot tell a synthetic root from a user root someone symlinked into
    /tmp — the same honesty rule as
    ``migration.profile_bindings._is_synthetic_root``."""
    tmp = Path(tempfile.gettempdir()).resolve()
    return path != tmp and tmp in path.parents


def _require_synthetic_path(path: Path, *, allow_user_data: bool,
                            subject: str) -> None:
    """Refuse any root outside ``tempfile.gettempdir()`` unless
    ``allow_user_data=True``. What is enforced is exactly that path rule;
    the flag is an UNVERIFIED caller assertion — no backup/rollback
    evidence and no user-confirmation record is validated when it is set
    (AGENTS.md rule 5; plan.md 原有 Assets-Skill 迁移)."""
    if allow_user_data or _is_synthetic_path(path):
        return
    raise RestoreError(
        "RESTORE_USER_DATA_CONFIRMATION_REQUIRED",
        f"{subject} is not under the system temp dir; the default refusal "
        "is a path-shape rule only, and running against a real user root "
        "additionally requires the documented backup/restore evidence and "
        "explicit user confirmation — collected out-of-band and asserted, "
        "not verified, by allow_user_data=True",
        detail=str(path))


def _under(candidate: Path, parent: Path) -> bool:
    return candidate == parent or parent in candidate.parents


# -- walking and hashing ------------------------------------------------------


def _file_sha256(path: Path) -> tuple[str, int]:
    hasher = hashlib.sha256()
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        with os.fdopen(descriptor, "rb") as stream:
            size = 0
            while True:
                chunk = stream.read(65536)
                if not chunk:
                    break
                size += len(chunk)
                hasher.update(chunk)
    except OSError as exc:
        raise RestoreError(
            "RESTORE_ENTRY_INVALID", "file is unreadable",
            detail=str(path)) from exc
    return "sha256:" + hasher.hexdigest(), size


def _walk_regular_files(base: Path, *, root_for_rel: Path,
                        exclude: Path | None = None) -> Iterator[tuple[str, Path]]:
    """Yield (posix-relpath, path) for every REGULAR file under ``base``,
    failing closed on symlinks/special files (never followed out) and on
    non-portable path shapes. ``exclude`` prunes one subtree entirely."""
    if not base.exists():
        return
    stack = [base]
    while stack:
        directory = stack.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda e: e.name)
        except OSError as exc:
            raise RestoreError(
                "RESTORE_ENTRY_INVALID", "directory is unreadable",
                detail=str(directory)) from exc
        for entry in entries:
            location = Path(entry.path)
            if exclude is not None and location == exclude:
                continue
            mode = entry.stat(follow_symlinks=False).st_mode
            if stat.S_ISLNK(mode):
                raise RestoreError(
                    "RESTORE_ENTRY_INVALID",
                    "a symlink stands in the snapshot's path; this tool "
                    "never follows links out of the recorded tree",
                    detail=str(location))
            relative = location.relative_to(root_for_rel).as_posix()
            if any(part in {"", ".", ".."} for part in relative.split("/")):
                raise RestoreError(
                    "RESTORE_ENTRY_INVALID", "path is not canonical",
                    detail=relative)
            if stat.S_ISDIR(mode):
                stack.append(location)
            elif stat.S_ISREG(mode):
                yield relative, location
            else:
                raise RestoreError(
                    "RESTORE_ENTRY_INVALID",
                    "a special file stands in the recorded tree",
                    detail=str(location))


def _revision_dirs(skill_root: Path) -> list[Path]:
    """The ``skill/<assetId>/<revision>`` directories, in a canonical order.
    Only numeric revision dirs count — the same rule
    ``library.store.SkillRevisionStore.list_revisions`` uses."""
    revisions: list[Path] = []
    if not skill_root.is_dir():
        return revisions
    for asset in sorted(p for p in skill_root.iterdir() if p.is_dir()):
        for child in sorted(p for p in asset.iterdir()
                            if p.is_dir() and p.name.isdigit()):
            revisions.append(child)
    return revisions


def _db_files(root: Path, *, require: bool) -> list[Path]:
    main = root.joinpath(*DB_RELATIVE)
    if require and not main.is_file():
        raise RestoreError(
            "RESTORE_DATA_ROOT_INVALID",
            "the data root carries no product database at state/agentbox.sqlite",
            detail=str(main))
    found = [main] if main.is_file() else []
    for sidecar in (Path(str(main) + suffix) for suffix in DB_SIDECAR_SUFFIXES):
        if not sidecar.exists():
            continue
        if sidecar.stat().st_size != 0:
            raise RestoreError(
                "RESTORE_DATA_ROOT_INVALID",
                "the database is not at rest (a live WAL sidecar carries "
                "un-checkpointed bytes); quiesce the root before backup or "
                "restore — this tool never copies a hot database",
                detail=str(sidecar))
        if sidecar.is_file():
            found.append(sidecar)
    return found


@dataclass(frozen=True)
class _Manifest:
    backup: Path
    data: dict

    @property
    def data_root(self) -> str:
        return str(self.data["dataRoot"])


def _load_manifest(backup: Path | str) -> _Manifest:
    b = Path(backup).resolve()
    path = b / "manifest.json"
    if not path.is_file():
        raise RestoreError(
            "RESTORE_BACKUP_INVALID",
            "the backup carries no manifest.json", detail=str(b))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RestoreError(
            "RESTORE_BACKUP_INVALID", "the backup manifest is unreadable",
            detail=str(path)) from exc
    if data.get("manifestVersion") != MANIFEST_VERSION:
        raise RestoreError(
            "RESTORE_BACKUP_INVALID",
            f"unsupported manifest version {data.get('manifestVersion')!r}",
            detail=str(b))
    return _Manifest(backup=b, data=data)


# -- snapshot -------------------------------------------------------------------


def snapshot(root: Path | str, *, backup_parent: Path | str | None = None,
             allow_user_data: bool = False) -> dict:
    """Copy the Skills slice (database file + ``assets/skill/**``) of one
    data root into a fresh timestamped backup directory and record the
    foreign ``assets/**`` bytes (mcp/, plugin/, catalogs/, approvals — see
    the module docstring) without copying them.

    ``backup_parent`` defaults to the system temp dir. Guards: the data
    root must be a real product root at rest; the backup may land neither
    inside the data root nor inside this repository (AGENTS.md rule 7); a
    non-synthetic root refuses unless ``allow_user_data`` is asserted
    (an unverified caller assertion). Any refusal leaves NO partial
    backup behind.
    """
    resolved = Path(root).resolve()
    _require_synthetic_path(resolved, allow_user_data=allow_user_data,
                            subject="the snapshotted data root")
    if not resolved.is_dir():
        raise RestoreError(
            "RESTORE_DATA_ROOT_INVALID", "the data root is not a directory",
            detail=str(resolved))
    db_files = _db_files(resolved, require=True)

    parent = (Path(backup_parent).resolve() if backup_parent is not None
              else Path(tempfile.gettempdir()).resolve())
    if _under(parent, resolved):
        raise RestoreError(
            "RESTORE_BACKUP_INSIDE_ROOT",
            "a backup must live outside the data root it protects — inside "
            "the root, damage to the root takes the backup with it",
            detail=str(parent))
    repo = _repo_root()
    if repo is not None and _under(parent, repo):
        raise RestoreError(
            "RESTORE_BACKUP_INSIDE_REPO",
            "backups never land inside the repository (AGENTS.md rule 7: "
            "credentials and user data never enter this repo — and neither "
            "do their copies)", detail=str(parent))

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S-%f")
    backup = parent / f"{BACKUP_DIR_PREFIX}{stamp}"
    while backup.exists():
        stamp += "x"
        backup = parent / f"{BACKUP_DIR_PREFIX}{stamp}"

    try:
        (backup / Path(*DB_RELATIVE)).parent.mkdir(parents=True)
        for file in db_files:
            relative = file.relative_to(resolved).as_posix()
            target = backup / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(file, target)

        skill_files: list[dict] = []
        skill_root = resolved / SKILL_RELATIVE
        for relative, location in _walk_regular_files(
                skill_root, root_for_rel=resolved):
            target = backup / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(location, target)
            digest, size = _file_sha256(target)
            skill_files.append({"path": relative, "sha256": digest,
                                "size": size})
        skill_trees = [
            {"path": revision.relative_to(resolved).as_posix(),
             "digest": runtime_artifact_tree_digest(backup / revision.relative_to(resolved))}
            for revision in _revision_dirs(skill_root)]

        database_entries = [
            {"path": file.relative_to(resolved).as_posix(),
             "sha256": _file_sha256(backup / file.relative_to(resolved))[0],
             "size": file.stat().st_size}
            for file in db_files]

        foreign_files = [
            {"path": relative,
             "sha256": _file_sha256(location)[0],
             "size": _file_sha256(location)[1]}
            for relative, location in _walk_regular_files(
                resolved / ASSETS_RELATIVE, root_for_rel=resolved,
                exclude=skill_root)]

        manifest = {
            "manifestVersion": MANIFEST_VERSION,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "dataRoot": str(resolved),
            "database": database_entries,
            "skillFiles": sorted(skill_files, key=lambda item: item["path"]),
            "skillTrees": sorted(skill_trees, key=lambda item: item["path"]),
            "foreignFiles": sorted(foreign_files,
                                   key=lambda item: item["path"]),
        }
        (backup / "manifest.json").write_text(
            json.dumps(manifest, sort_keys=True, indent=1),
            encoding="utf-8")
    except BaseException:
        shutil.rmtree(backup, ignore_errors=True)
        raise

    return {
        "backup": str(backup),
        "dataRoot": str(resolved),
        "databaseFiles": len(database_entries),
        "skillFiles": len(skill_files),
        "skillTrees": len(skill_trees),
        "foreignFiles": len(foreign_files),
    }


# -- verify_backup ---------------------------------------------------------------


def verify_backup(backup: Path | str) -> dict:
    """Re-check a backup against its own manifest: every recorded database
    and skill-tree file is re-hashed from the backup copy and every
    ``skill/<assetId>/<revision>`` digest is re-derived from it. Any
    divergence raises the typed ``RESTORE_MANIFEST_MISMATCH`` listing ALL
    findings; foreign files are not part of the backup and are therefore
    not re-hashable here (their baseline is checked by :func:`restore`).
    """
    manifest = _load_manifest(backup)
    data = manifest.data
    failures: list[str] = []
    checked = 0
    for section in ("database", "skillFiles"):
        for item in data[section]:
            location = manifest.backup / item["path"]
            if not location.is_file():
                failures.append(f"{item['path']}: missing from the backup")
                continue
            digest, size = _file_sha256(location)
            if digest != item["sha256"] or size != item["size"]:
                failures.append(
                    f"{item['path']}: backup copy is {digest}/{size}, "
                    f"manifest says {item['sha256']}/{item['size']}")
            checked += 1
    for item in data["skillTrees"]:
        location = manifest.backup / item["path"]
        if not location.is_dir():
            failures.append(f"{item['path']}: revision dir missing")
            continue
        digest = runtime_artifact_tree_digest(location)
        if digest != item["digest"]:
            failures.append(
                f"{item['path']}: backup tree digest {digest}, manifest "
                f"says {item['digest']}")
        checked += 1
    if failures:
        raise RestoreError(
            "RESTORE_MANIFEST_MISMATCH",
            "the backup no longer matches its manifest",
            detail="; ".join(failures))
    return {
        "backup": str(manifest.backup),
        "dataRoot": manifest.data_root,
        "entriesChecked": checked,
        "foreignFilesRecorded": len(data["foreignFiles"]),
        "ok": True,
    }


# -- restore ----------------------------------------------------------------------


def _current_foreign_state(root: Path) -> dict[str, dict]:
    skill_root = root / SKILL_RELATIVE
    return {
        relative: {"sha256": _file_sha256(location)[0],
                   "size": _file_sha256(location)[1]}
        for relative, location in _walk_regular_files(
            root / ASSETS_RELATIVE, root_for_rel=root, exclude=skill_root)
    }


def _restore_slice(manifest: _Manifest, dest: Path) -> None:
    """Write exactly what the snapshot covered: the database files and the
    skill slice. The skill replacement stages under ``assets/`` and renames
    into place (the same staging+rename rule the revision store installs
    with), so a mid-copy failure can never leave a half-restored slice."""
    for item in manifest.data["database"]:
        target = dest / item["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(manifest.backup / item["path"], target)
    for suffix in DB_SIDECAR_SUFFIXES:
        stray = Path(dest.joinpath(*DB_RELATIVE).__str__() + suffix)
        if stray.exists() and stray.name not in {
                Path(item["path"]).name for item in manifest.data["database"]}:
            stray.unlink()

    skill_dest = dest / SKILL_RELATIVE
    parent = skill_dest.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = parent / f".skill-restore-staging-{os.getpid()}"
    staging.mkdir(exist_ok=True)
    try:
        for item in manifest.data["skillFiles"]:
            target = staging / Path(*Path(item["path"]).parts[2:])
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(manifest.backup / item["path"], target)
            target.chmod(0o644)
        if skill_dest.exists():
            shutil.rmtree(skill_dest)
        if not any(True for _ in staging.iterdir()):
            staging.rmdir()
        else:
            os.rename(staging, skill_dest)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def restore(backup: Path | str, into_root: Path | str, *,
            allow_foreign_root: bool = False,
            allow_user_data: bool = False) -> dict:
    """Restore exactly what :func:`snapshot` covered — the database file
    and the ``assets/skill/**`` slice — into a data root, and return the
    byte-comparison report proving it.

    Guards, in order, all BEFORE any write:

    1. destination synthetic-root guard (the same path-shape rule as the
       migration's; ``allow_user_data=True`` is the same unverified caller
       assertion);
    2. manifest validity (``RESTORE_BACKUP_INVALID``);
    3. **destination identity** — the root must be the one recorded in the
       manifest unless ``allow_foreign_root=True`` is asserted;
    4. the destination database must be at rest (no hot WAL sidecar);
    5. **foreign baseline** — on the recorded root the current non-skill
       ``assets/**`` bytes must still equal what the snapshot recorded;
       ANY divergence (changed, missing or extra foreign file) refuses
       with ``RESTORE_FOREIGN_DRIFT`` and writes nothing: the tool will
       not complete a restore over bytes it recorded but does not own and
       cannot re-derive. On an ``allow_foreign_root`` destination this
       check is skipped by necessity and the report says
       ``foreignVerified: false`` — restored there means the skill slice
       and the database files only, foreign bytes on that root are then
       the other owners' problem, exactly as plan.md assigns it.

    After the staged write the function re-hashes every restored file and
    re-derives every restored revision tree digest at the destination and
    compares against the manifest (``RESTORE_MANIFEST_MISMATCH`` on any
    surprise). The operation is idempotent: restoring twice leaves the
    same bytes. The backup itself is never modified or deleted, and the
    original root is never deleted — only its Skills slice is replaced."""
    dest = Path(into_root).resolve()
    _require_synthetic_path(dest, allow_user_data=allow_user_data,
                            subject="the restore destination data root")
    manifest = _load_manifest(backup)
    if not allow_foreign_root and str(dest) != manifest.data_root:
        raise RestoreError(
            "RESTORE_FOREIGN_ROOT",
            "the destination is not the data root this backup was taken "
            "of; restoring into an unrelated root needs the explicit "
            "allow_foreign_root assertion",
            detail=f"destination {dest} != recorded {manifest.data_root}")
    if not dest.is_dir():
        raise RestoreError(
            "RESTORE_FOREIGN_ROOT",
            "the destination data root does not exist", detail=str(dest))
    _db_files(dest, require=False)
    foreign_mismatches: list[str] = []
    if not allow_foreign_root:
        expected = {item["path"]: item for item in manifest.data["foreignFiles"]}
        current = _current_foreign_state(dest)
        for path, item in expected.items():
            now_item = current.get(path)
            if now_item is None:
                foreign_mismatches.append(f"{path}: foreign file is gone")
            elif now_item["sha256"] != item["sha256"]:
                foreign_mismatches.append(f"{path}: foreign bytes changed")
        for path in current:
            if path not in expected:
                foreign_mismatches.append(
                    f"{path}: foreign file was added after the snapshot")

    if foreign_mismatches:
        raise RestoreError(
            "RESTORE_FOREIGN_DRIFT",
            "non-skill asset bytes no longer match what the snapshot "
            "recorded; refusing to restore onto a root whose foreign "
            "content diverged (zero writes) — those kinds belong to their "
            "old business owners (plan.md 原有 Assets-Skill 迁移), so "
            "resolve their state out-of-band first, then restore",
            detail="; ".join(foreign_mismatches))

    _restore_slice(manifest, dest)

    failures: list[str] = []
    for item in (manifest.data["database"] + manifest.data["skillFiles"]):
        location = dest / item["path"]
        if not location.is_file():
            failures.append(f"{item['path']}: not restored")
            continue
        digest, size = _file_sha256(location)
        if digest != item["sha256"] or size != item["size"]:
            failures.append(
                f"{item['path']}: destination is {digest}/{size}, manifest "
                f"says {item['sha256']}/{item['size']}")
    trees = []
    for item in manifest.data["skillTrees"]:
        location = dest / item["path"]
        actual = (runtime_artifact_tree_digest(location)
                  if location.is_dir() else None)
        if actual != item["digest"]:
            failures.append(
                f"{item['path']}: destination tree digest {actual}, manifest "
                f"says {item['digest']}")
        trees.append({"path": item["path"], "digest": item["digest"],
                      "match": actual == item["digest"]})
    if failures:
        raise RestoreError(
            "RESTORE_MANIFEST_MISMATCH",
            "the destination does not match the manifest after the restore "
            "wrote it — the backup remains intact and restorable",
            detail="; ".join(failures))
    return {
        "backup": str(manifest.backup),
        "destination": str(dest),
        "databaseFilesRestored": len(manifest.data["database"]),
        "skillFilesRestored": len(manifest.data["skillFiles"]),
        "skillTrees": trees,
        "foreignVerified": not allow_foreign_root,
        "foreignFilesChecked": (0 if allow_foreign_root
                                else len(manifest.data["foreignFiles"])),
        "manifestOk": True,
    }


__all__ = ["MANIFEST_VERSION", "RestoreError", "restore", "snapshot",
           "verify_backup"]
