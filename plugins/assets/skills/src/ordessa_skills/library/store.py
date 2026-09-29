"""The skill revision store: staging + rename, content-addressed (store.py).

Ported unchanged from `plugins/assets/src/ordessa_assets/server/store.py`
@ 752f148b1b (research-and-reuse.md 不可变修订仓 row: 直接迁算法和
`skill/<assetId>/<revision>` 布局；保留 treeDigest 字节规则).

Disk layout and digest spelling are byte-compatible with the legacy
`server-compat` store: `<root>/skill/<asset_id>/<revision>/`, tree digest v1
via `pacthold.resource_contracts.runtime_artifact_tree_digest`.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from pacthold_runtime_compat.resource_contracts.runtime_artifacts import (
    runtime_artifact_tree_digest,
)

from ..api.errors import SkillAssetError
from ..api.identity import ASSET_ID
from ..formats.agent_skills.frontmatter import parse_frontmatter
from ..formats.agent_skills.validator import validate_skill_directory


class SkillRevisionStore:
    """Install skill directories as immutable revisions under one assets root."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def revision_dir(self, asset_id: str, revision: int) -> Path:
        return self.root / "skill" / asset_id / str(revision)

    def install(self, source: Path | str, *, asset_id: str, revision: int,
                directory_name: str | None = None,
                source_ref: str = "local:import") -> dict[str, Any]:
        """Validate and publish one skill revision; returns its facts.

        The copy is staged and renamed, so a failure leaves the previous
        revision (or nothing) in place — an install never lands half-way.
        Stored files are read-only bytes (0o644); no executable bit travels.
        """
        if ASSET_ID.fullmatch(asset_id) is None:
            raise SkillAssetError("SKILL_ASSET_INVALID",
                                  "asset_id must be a lowercase slug", detail=asset_id)
        if not isinstance(revision, int) or revision < 1:
            raise SkillAssetError("SKILL_ASSET_INVALID", "revision must be >= 1")
        validated = validate_skill_directory(Path(source),
                                             directory_name=directory_name)

        destination = self.revision_dir(asset_id, revision)
        if destination.exists():
            raise SkillAssetError(
                "SKILL_REVISION_EXISTS",
                f"revision {revision} of {asset_id} already exists")
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix="skill-staging-",
                                        dir=str(destination.parent)))
        try:
            for entry in validated.entries:
                target = staging / entry.relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(entry.path, target)
                target.chmod(0o644)
            digest = runtime_artifact_tree_digest(staging)
            if destination.exists():
                raise SkillAssetError(
                    "SKILL_REVISION_EXISTS",
                    f"revision {revision} of {asset_id} already exists")
            os.rename(staging, destination)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return {
            "asset_id": asset_id,
            "kind": "skill",
            "revision": revision,
            "tree_digest": digest,
            "name": validated.facts.name,
            "description": validated.facts.description,
            "metadata": dict(validated.facts.metadata),
            "retained_fields": dict(validated.facts.retained),
            "files": len(validated.entries),
            "total_bytes": validated.total_bytes,
            "scripts": validated.scripts,
            "source": source_ref,
        }

    def verify(self, *, asset_id: str, revision: int, expected_digest: str) -> bool:
        """Re-derive the stored revision's digest and compare."""
        directory = self.revision_dir(asset_id, revision)
        if not directory.is_dir():
            raise SkillAssetError("SKILL_ASSET_MISSING", "the skill revision is not installed")
        return runtime_artifact_tree_digest(directory) == expected_digest

    def revision_digest(self, *, asset_id: str, revision: int) -> str:
        directory = self.revision_dir(asset_id, revision)
        if not directory.is_dir():
            raise SkillAssetError("SKILL_ASSET_MISSING", "the skill revision is not installed")
        return runtime_artifact_tree_digest(directory)

    def read_metadata(self, *, asset_id: str, revision: int) -> dict[str, Any]:
        """Re-read the frontmatter facts of one stored revision."""
        directory = self.revision_dir(asset_id, revision)
        if not directory.is_dir():
            raise SkillAssetError("SKILL_ASSET_MISSING", "the skill revision is not installed")
        facts = parse_frontmatter(
            (directory / "SKILL.md").read_text(encoding="utf-8", errors="replace"))
        return {
            "asset_id": asset_id,
            "revision": revision,
            "tree_digest": self.revision_digest(asset_id=asset_id, revision=revision),
            "name": facts.name,
            "description": facts.description,
            "metadata": dict(facts.metadata),
            "retained_fields": dict(facts.retained),
        }

    def list_revisions(self, asset_id: str) -> list[dict[str, Any]]:
        base = self.root / "skill" / asset_id
        if not base.is_dir():
            raise SkillAssetError("SKILL_ASSET_MISSING", "the asset has no revisions")
        revisions = []
        for child in sorted(base.iterdir(), key=lambda item: int(item.name)
                            if item.name.isdigit() else 0):
            if not child.is_dir() or not child.name.isdigit():
                continue
            revisions.append({
                "revision": int(child.name),
                "digest": runtime_artifact_tree_digest(child),
            })
        return revisions
