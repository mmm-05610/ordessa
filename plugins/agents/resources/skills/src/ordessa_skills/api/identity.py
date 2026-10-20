"""Asset identity and revision facts (data-model.md §1)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping

#: The catalogue kinds the shared `server_assets` table has always carried.
#: This domain only ever *issues* `skill`; the rest stay for wire compatibility.
ASSET_KINDS = ("skill", "mcp", "command", "plugin")

ASSET_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
SKILL_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")

#: One skill's files and bytes are bounded: a skill is instructions plus small
#: resources, and an unbounded install would be a copy of the whole disk.
MAX_ASSET_ENTRIES = 512
MAX_ASSET_BYTES = 32 * 1024 * 1024
MAX_FRONTMATTER_BYTES = 64 * 1024
MAX_DESCRIPTION_CHARS = 1024
MAX_COMPATIBILITY_CHARS = 500


@dataclass(frozen=True)
class SkillRevisionFacts:
    """The facts one published revision carries — no content, no host paths."""

    asset_id: str
    revision: int
    tree_digest: str
    name: str
    description: str
    metadata: Mapping[str, str] = field(default_factory=dict)
    retained_fields: Mapping[str, Any] = field(default_factory=dict)
    file_count: int = 0
    total_bytes: int = 0
    scripts: tuple[str, ...] = ()
    source: str = "local:import"

    def public_dict(self) -> dict[str, Any]:
        return {
            "assetId": self.asset_id,
            "revision": self.revision,
            "treeDigest": self.tree_digest,
            "name": self.name,
            "description": self.description,
            "metadata": dict(self.metadata),
            "retainedFields": _jsonable(self.retained_fields),
            "fileCount": self.file_count,
            "totalBytes": self.total_bytes,
            "scripts": list(self.scripts),
            "source": self.source,
        }


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
