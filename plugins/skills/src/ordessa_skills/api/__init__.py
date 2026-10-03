"""Domain contracts: pure types, errors, the evidence ladder and ports.

Imports nothing outside the stdlib and this area (plan.md 目标目录: 纯类型/
错误/身份；无实现加载).
"""
from __future__ import annotations

from .errors import (
    AssetDomainError,
    BindingError,
    CatalogError,
    ImportError_,
    PreviewError,
    ProjectionError,
    SkillAssetError,
)
from .evidence import (
    LADDER,
    LEVELS,
    LOADED,
    PROJECTED,
    PROOF_REQUIREMENTS,
    SELECTED,
    STORED,
    UNCONFIRMED,
    UNKNOWN,
    USED,
    attest,
    highest,
)
from .identity import (
    ASSET_ID,
    ASSET_KINDS,
    MAX_ASSET_BYTES,
    MAX_ASSET_ENTRIES,
    MAX_COMPATIBILITY_CHARS,
    MAX_DESCRIPTION_CHARS,
    MAX_FRONTMATTER_BYTES,
    SKILL_NAME,
    SkillRevisionFacts,
)
from .ports import (
    ProfileRegistrationPort,
    SkillBindingFacet,
)

__all__ = [
    "AssetDomainError", "BindingError", "CatalogError", "ImportError_",
    "PreviewError", "ProjectionError", "SkillAssetError",
    "LADDER", "LEVELS", "LOADED", "PROJECTED", "PROOF_REQUIREMENTS",
    "SELECTED", "STORED", "UNCONFIRMED", "UNKNOWN", "USED", "attest",
    "highest",
    "ASSET_ID", "ASSET_KINDS", "MAX_ASSET_BYTES", "MAX_ASSET_ENTRIES",
    "MAX_COMPATIBILITY_CHARS", "MAX_DESCRIPTION_CHARS",
    "MAX_FRONTMATTER_BYTES", "SKILL_NAME", "SkillRevisionFacts",
    "ProfileRegistrationPort", "SkillBindingFacet",
]
