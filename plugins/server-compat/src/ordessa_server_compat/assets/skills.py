"""Order 58: the skill asset - one directory, validated, content-addressed.

The cross-family format is the Agent Skills one: a skill is a directory whose
``SKILL.md`` carries YAML frontmatter with at least ``name`` (lowercase,
hyphenated) and ``description``, and the directory may hold scripts and
resources. This module owns the *store* half: install a directory as a
revision under ``<root>/<kind>/<asset-id>/<revision>/``, re-derive its tree
digest, and expose the frontmatter facts a listing needs. The digest is the
one the runtime-artifact contract already speaks (tree digest v1), so a
materialised projection can be verified against it by the existing machinery.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from pacthold.resource_contracts.runtime_artifacts import runtime_artifact_tree_digest

#: One skill's files and bytes are bounded: a skill is instructions plus small
#: resources, and an unbounded install would be a copy of the whole disk.
MAX_ASSET_ENTRIES = 512
MAX_ASSET_BYTES = 32 * 1024 * 1024
#: The two required frontmatter fields, spelled as the specification spells
#: them. `name` is a lowercase hyphenated slug; `description` is prose.
_SKILL_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---(\r?\n|\Z)", re.S)
_FIELD = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$")


class SkillAssetError(RuntimeError):
    """A typed refusal of one skill install or read."""

    def __init__(self, code: str, message: str, *, name: str | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.name = name


def parse_skill_frontmatter(text: str) -> dict[str, str]:
    """The two required fields, or a typed refusal.

    The parse is deliberately minimal - flat ``key: value`` lines between the
    ``---`` fences, with optional surrounding quotes - because the format only
    requires two scalars. Anything else stays out of the contract rather than
    being guessed at.
    """
    match = _FRONTMATTER.match(text)
    if match is None:
        raise SkillAssetError("SKILL_FRONTMATTER_MISSING", "SKILL.md has no frontmatter")
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        field = _FIELD.match(line)
        if field is None:
            raise SkillAssetError(
                "SKILL_FRONTMATTER_INVALID", f"frontmatter line is not a scalar: {line[:64]!r}",
            )
        value = field.group(2).strip().strip('"').strip("'")
        if value[:1] in {"[", "{", "|", ">"}:
            # Flow collections and block scalars are YAML the two-field
            # contract does not need; guessing at them is how a store starts
            # disagreeing with the specification.
            raise SkillAssetError(
                "SKILL_FRONTMATTER_INVALID",
                f"frontmatter field {field.group(1)!r} is not a scalar",
            )
        fields.setdefault(field.group(1), value)
    name = fields.get("name", "")
    if not name or _SKILL_NAME.fullmatch(name) is None:
        raise SkillAssetError(
            "SKILL_NAME_INVALID",
            "name must be a lowercase hyphenated slug",
        )
    if not fields.get("description"):
        raise SkillAssetError("SKILL_DESCRIPTION_MISSING", "description is required")
    return {"name": name, "description": fields["description"]}


def _walk_bounded(root: Path) -> list[tuple[str, Path]]:
    """Every regular file under the skill directory, bounded and link-free."""
    files: list[tuple[str, Path]] = []
    total = 0
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames.sort()
        for filename in sorted(filenames):
            path = Path(directory) / filename
            info = os.lstat(path)
            if not os.path.isfile(path) or os.path.islink(path):
                raise SkillAssetError(
                    "SKILL_ASSET_INVALID", "a skill may hold only regular files",
                    name=str(path.relative_to(root)),
                )
            total += info.st_size
            if len(files) >= MAX_ASSET_ENTRIES or total > MAX_ASSET_BYTES:
                raise SkillAssetError(
                    "SKILL_ASSET_OUTSIDE_BOUNDS", "the skill exceeds the install bounds",
                )
            files.append((str(path.relative_to(root)), path))
    return files


class SkillAssetStore:
    """Install skill directories as revisions under one assets root."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def revision_dir(self, asset_id: str, revision: int) -> Path:
        return self.root / "skill" / asset_id / str(revision)

    def install(self, source: Path | str, *, asset_id: str, revision: int) -> dict[str, Any]:
        """Validate and publish one skill revision; returns its facts.

        The copy is staged and renamed, so a failure leaves the previous
        revision (or nothing) in place - an install never lands half-way.
        """
        source = Path(source)
        if not source.is_dir() or source.is_symlink():
            raise SkillAssetError("SKILL_ASSET_INVALID", "the skill source must be a directory")
        skill_md = source / "SKILL.md"
        if skill_md.is_symlink() or not skill_md.is_file():
            raise SkillAssetError("SKILL_ASSET_INVALID", "a skill needs a regular SKILL.md")
        frontmatter = parse_skill_frontmatter(skill_md.read_text(encoding="utf-8", errors="replace"))
        files = _walk_bounded(source)
        if not files:
            raise SkillAssetError("SKILL_ASSET_INVALID", "the skill directory is empty")

        destination = self.revision_dir(asset_id, revision)
        if destination.exists():
            raise SkillAssetError(
                "SKILL_REVISION_EXISTS", f"revision {revision} of {asset_id} already exists",
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix="skill-staging-", dir=str(destination.parent)))
        try:
            for relative, path in files:
                target = staging.joinpath(*relative.split("/"))
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
                os.chmod(target, 0o644)
            digest = runtime_artifact_tree_digest(staging)
            if destination.exists():
                raise SkillAssetError(
                    "SKILL_REVISION_EXISTS", f"revision {revision} of {asset_id} already exists",
                )
            os.rename(staging, destination)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return {
            "asset_id": asset_id,
            "kind": "skill",
            "revision": revision,
            "tree_digest": digest,
            "name": frontmatter["name"],
            "description": frontmatter["description"],
            "files": len(files),
        }

    def verify(self, *, asset_id: str, revision: int, expected_digest: str) -> bool:
        """Re-derive the stored revision's digest and compare."""
        directory = self.revision_dir(asset_id, revision)
        if not directory.is_dir():
            raise SkillAssetError("SKILL_ASSET_MISSING", "the skill revision is not installed")
        return runtime_artifact_tree_digest(directory) == expected_digest
