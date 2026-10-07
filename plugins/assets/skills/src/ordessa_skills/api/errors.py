"""Typed refusals of one skills operation (docs/design/skills-v2/data-model.md
error codes).

Codes follow the legacy store's spelling so wire responses stay comparable;
new codes introduced by this domain are listed here once and referenced by
tests and the contracts documents.
"""
from __future__ import annotations


class AssetDomainError(RuntimeError):
    """A typed refusal; `code` is the stable identifier, never prose."""

    def __init__(self, code: str, message: str, *, detail: str | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.detail = detail


class SkillAssetError(AssetDomainError):
    """One skill install or read was refused."""


class CatalogError(AssetDomainError):
    """One catalog operation was refused."""


class BindingError(AssetDomainError):
    """One binding operation was refused."""


class ImportError_(AssetDomainError):
    """One bounded-import session step was refused."""


class ProjectionError(AssetDomainError):
    """One projection/evidence operation was refused."""


class PreviewError(AssetDomainError):
    """One preview request was refused."""
