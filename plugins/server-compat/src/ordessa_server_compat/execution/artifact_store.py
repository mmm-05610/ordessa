"""Order 57: the artifact store — version directories, references, atomic install.

"Install / update / rollback a family's harness runtime" becomes a product
capability through this store:

* **Version directories**: `<root>/<family>/<version>/` holds one installed
  runtime; the contents' tree digest (v1, the same cross-language algorithm
  the Worker re-derives) is re-derived at install time and must match the
  declared digest — a mismatch leaves nothing behind.
* **References**: "which version does this family run" is a *reference* (a
  small JSON pointer per family), never an in-place overwrite — so an update
  adds a sibling directory and moves the reference, a rollback moves it back,
  and a session already running against the previous directory is untouched.
* **Atomic install**: content is staged in `<root>/.staging/<unique>/` and
  only renamed into place after the digest check passes; a failure cleans the
  stage and the family's installed set is unchanged.

The store is machine-local and address-agnostic: the caller (the assembly or
an operator) resolves the root through the same mount-token rules as every
other path — no host path enters any record.
"""
from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path
from typing import Any

from pacthold.resource_contracts.runtime_artifacts import (
    runtime_artifact_tree_digest,
)


class ArtifactStoreError(RuntimeError):
    """A typed store failure; the message carries no host path."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def _make_tree_writable(root: Path) -> None:
    """Grant owner-write on every staged directory (content untouched).

    Read-only sources (published closures) copy their modes into the stage;
    the rename and later housekeeping need owner-write on directories."""
    root.chmod(0o755)
    for current, _dirs, _names in os.walk(root):
        try:
            Path(current).chmod(0o755)
        except OSError:
            pass



class ArtifactStore:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def _family_dir(self, family: str, version: str) -> Path:
        return self.root / family / version

    def _staging(self) -> Path:
        staging = self.root / ".staging"
        staging.mkdir(parents=True, exist_ok=True)
        return staging

    def incoming_dir(self, token: str) -> Path:
        """The staged-source directory for one incoming token (safe name)."""
        if not token or "/" in token or token.startswith("."):
            raise ArtifactStoreError("ARTIFACT_SOURCE_INVALID", "invalid incoming token")
        directory = self.root / ".incoming" / token
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def install(self, family: str, version: str, source: Path,
                declared_digest: str) -> dict[str, Any]:
        """Install `source` as `<family>/<version>` after digest re-derivation.

        The digest is re-derived from the staged copy (not trusted from the
        source) and must match `declared_digest` before anything is visible;
        a failure removes the stage and re-raises, so the family's installed
        set and the current reference are unchanged.
        """
        if not family or "/" in family or family.startswith("."):
            raise ArtifactStoreError("ARTIFACT_FAMILY_INVALID", "invalid family name")
        if not version or "/" in version or version.startswith("."):
            raise ArtifactStoreError("ARTIFACT_VERSION_INVALID", "invalid version name")
        source = Path(source)
        if not source.is_dir():
            raise ArtifactStoreError(
                "ARTIFACT_SOURCE_MISSING", f"the source is not a directory",
            )
        destination = self._family_dir(family, version)
        if destination.exists():
            raise ArtifactStoreError(
                "ARTIFACT_VERSION_EXISTS", f"{family}/{version} is already installed",
            )
        # A unique staging directory per call: a PID-based name would collide
        # across installs within one long-lived process.
        import uuid

        staging = self._staging() / f"{family}-{version}-{uuid.uuid4().hex}"
        try:
            # copytree creates the staging directory itself (its default
            # requires the destination to be absent — exactly the atomicity
            # this store wants).
            shutil.copytree(source, staging, symlinks=False)
            digest = runtime_artifact_tree_digest(staging)
            if digest != declared_digest:
                raise ArtifactStoreError(
                    "ARTIFACT_DIGEST_MISMATCH",
                    f"staged tree digest {digest} does not match the declared "
                    f"{declared_digest}",
                )
            # A read-only source (the builder's published closure is 0555)
            # copies its modes into the stage; those modes make the staged
            # tree itself non-writable, and `rename` of a directory tree
            # requires traversing/writing entries. Normalize the staged
            # directories to owner-writable before the rename — the digest
            # does not cover modes, so this is not a content change.
            _make_tree_writable(staging)
            destination.parent.mkdir(parents=True, exist_ok=True)
            staging.rename(destination)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        summary = self.summary(family, version)
        return {"family": family, "version": version, "digest": digest, **summary}

    def installed(self, family: str) -> list[dict[str, Any]]:
        """The family's installed versions, oldest first by name."""
        family_dir = self.root / family
        if not family_dir.is_dir():
            return []
        return sorted(
            item.name for item in family_dir.iterdir()
            if item.is_dir() and not item.name.startswith(".")
        )

    def summary(self, family: str, version: str) -> dict[str, Any]:
        directory = self._family_dir(family, version)
        if not directory.is_dir():
            raise ArtifactStoreError("ARTIFACT_VERSION_MISSING", "version not installed")
        entries = 0
        total_bytes = 0
        for current, _dirs, names in os.walk(directory):
            for name in names:
                path = Path(current, name)
                try:
                    info = path.lstat()
                except OSError:
                    continue
                if stat.S_ISREG(info.st_mode):
                    entries += 1
                    total_bytes += info.st_size
        return {"entries": entries, "bytes": total_bytes}

    def current_reference(self, family: str) -> str | None:
        reference = self.root / family / ".current"
        if not reference.is_file():
            return None
        return reference.read_text(encoding="utf-8").strip() or None

    def set_current_reference(self, family: str, version: str) -> None:
        if version not in self.installed(family):
            raise ArtifactStoreError(
                "ARTIFACT_VERSION_MISSING", f"{family}/{version} is not installed",
            )
        reference = self.root / family / ".current"
        reference.parent.mkdir(parents=True, exist_ok=True)
        reference.write_text(version, encoding="utf-8")

    def rollback(self, family: str, version: str) -> None:
        """Point the family back at an installed version (references only)."""
        if version not in self.installed(family):
            raise ArtifactStoreError(
                "ARTIFACT_VERSION_MISSING", f"{family}/{version} is not installed",
            )
        self.set_current_reference(family, version)


__all__ = ["ArtifactStore", "ArtifactStoreError"]
