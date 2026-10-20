"""Agent Skills YAML frontmatter: canonical validation with retention.

The legacy regex parser accepted only flat scalars; the official format
allows nested `metadata` and extra fields, so this module speaks YAML
(`yaml.SafeLoader`, duplicate keys refused, input byte-bounded) and keeps
every legal field it does not interpret.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import yaml

from ...api.errors import SkillAssetError
from ...api.identity import (
    MAX_COMPATIBILITY_CHARS,
    MAX_DESCRIPTION_CHARS,
    MAX_FRONTMATTER_BYTES,
    SKILL_NAME,
)

_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---(\r?\n|\Z)", re.S)


class _StrictSafeLoader(yaml.SafeLoader):
    """SafeLoader that refuses duplicate mapping keys instead of last-winning."""


def _construct_mapping(loader: yaml.SafeLoader, node: yaml.Node, deep: bool = False):
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:  # unhashable key
            raise yaml.YAMLError("unhashable mapping key") from exc
        if duplicate:
            raise yaml.YAMLError(f"duplicate key {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_StrictSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


@dataclass(frozen=True)
class FrontmatterFacts:
    name: str
    description: str
    metadata: dict[str, str] = field(default_factory=dict)
    retained: dict[str, Any] = field(default_factory=dict)
    body: str = ""


def _split_frontmatter(text: str) -> tuple[str, str]:
    match = _FRONTMATTER.match(text)
    if match is None:
        raise SkillAssetError("SKILL_FRONTMATTER_MISSING", "SKILL.md has no frontmatter")
    block, body = match.group(1), text[match.end():]
    if len(block.encode("utf-8")) > MAX_FRONTMATTER_BYTES:
        raise SkillAssetError(
            "SKILL_FRONTMATTER_INVALID",
            f"frontmatter exceeds {MAX_FRONTMATTER_BYTES} bytes")
    return block, body


def _load_document(block: str) -> dict[str, Any]:
    try:
        document = yaml.load(block, Loader=_StrictSafeLoader)
    except (yaml.YAMLError, TypeError, ValueError) as exc:
        raise SkillAssetError(
            "SKILL_FRONTMATTER_INVALID", f"frontmatter is not valid YAML: {exc}")
    if not isinstance(document, dict):
        raise SkillAssetError(
            "SKILL_FRONTMATTER_INVALID", "frontmatter must be a YAML mapping")
    return document


def parse_frontmatter(text: str, *, directory_name: str | None = None) -> FrontmatterFacts:
    """The required fields plus everything legal the format lets a skill carry.

    `directory_name` — when the caller knows the skill folder's own name —
    enforces the official rule that `name` matches it.
    """
    block, body = _split_frontmatter(text)
    document = _load_document(block)

    name = document.get("name")
    if not isinstance(name, str) or not name or len(name) > 64 \
            or SKILL_NAME.fullmatch(name) is None:
        raise SkillAssetError(
            "SKILL_NAME_INVALID", "name must be a lowercase hyphenated slug (1-64)")
    if directory_name is not None and name != directory_name:
        raise SkillAssetError(
            "SKILL_NAME_MISMATCH",
            f"frontmatter name {name!r} does not match directory {directory_name!r}")

    description = document.get("description")
    if not isinstance(description, str) or not description:
        raise SkillAssetError("SKILL_DESCRIPTION_MISSING", "description is required")
    if len(description) > MAX_DESCRIPTION_CHARS:
        raise SkillAssetError(
            "SKILL_DESCRIPTION_INVALID",
            f"description exceeds {MAX_DESCRIPTION_CHARS} characters")

    metadata = document.get("metadata")
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict) or \
            not all(isinstance(key, str) and isinstance(value, str)
                    for key, value in metadata.items()):
        raise SkillAssetError(
            "SKILL_FRONTMATTER_INVALID", "metadata must map strings to strings")

    compatibility = document.get("compatibility")
    if compatibility is not None and (
            not isinstance(compatibility, str) or not 1 <= len(compatibility)
            or len(compatibility) > MAX_COMPATIBILITY_CHARS):
        raise SkillAssetError(
            "SKILL_FRONTMATTER_INVALID",
            f"compatibility must be 1-{MAX_COMPATIBILITY_CHARS} characters")
    for textual in ("license", "allowed-tools"):
        value = document.get(textual)
        if value is not None and not isinstance(value, str):
            raise SkillAssetError(
                "SKILL_FRONTMATTER_INVALID", f"{textual} must be a string")

    retained = {key: value for key, value in document.items()
                if key not in {"name", "description", "metadata"}}
    return FrontmatterFacts(name=name, description=description,
                            metadata=dict(metadata), retained=retained, body=body)
