"""The Skills content library: revision store, records, catalog, import, revisions.

Legacy provenance: `plugins/assets/src/ordessa_assets/server/{store,records,
catalog,import_transfer}.py` @ 752f148b1b (research-and-reuse.md rows 不可变
修订仓 / 分块导入 / 目录/版本/元数据: 直接迁算法与 `skill/<assetId>/<revision>`
布局). `revisions.py` and `diff.py` are new: they carry the T04 explicit
approval semantics (docs/design/skills-v2/README.md §内容修订与使用修订,
data-model.md §内容与版本) and the revision-to-revision diff (legacy
`server/service.py` diff/preview rows, plan.md 原有 Assets-Skill 迁移 split).

Boundaries: this area imports only `api`, `formats`, the stdlib and `pacthold`
(AGENTS.md rule 3). It never imports the host, Profile, Harness or Chat, and
it never executes skill content.
"""
from __future__ import annotations

from .catalog import KINDS as CATALOG_KINDS
from .catalog import CatalogStore, parse_index
from .diff import (
    MAX_DIFF_TEXT_BYTES,
    MAX_PREVIEW_BYTES,
    diff_revisions,
    file_map,
    preview_file,
    text_diff,
)
from .import_transfer import (
    MAX_CHUNK_BYTES,
    PREVIEW_TEXT_BYTES,
    SESSION_TTL_SECONDS,
    ImportService,
)
from .records import (
    AssetRecords,
    BindingCasPort,
    asset_view,
    now,
    opaque_id,
)
from .revisions import (
    RevisionApprovalStore,
    RevisionRetention,
    git_source,
    local_source,
    parse_source,
    publish_revision,
)
from .store import SkillRevisionStore

__all__ = [
    "AssetRecords", "BindingCasPort", "CATALOG_KINDS", "CatalogStore",
    "ImportService", "MAX_CHUNK_BYTES", "MAX_DIFF_TEXT_BYTES",
    "MAX_PREVIEW_BYTES", "PREVIEW_TEXT_BYTES", "RevisionApprovalStore",
    "RevisionRetention", "SESSION_TTL_SECONDS", "SkillRevisionStore",
    "asset_view", "diff_revisions", "file_map", "git_source", "local_source",
    "now", "opaque_id", "parse_index", "parse_source", "preview_file",
    "publish_revision", "text_diff",
]
