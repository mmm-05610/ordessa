"""Provider descriptors for the C1 layer.

``ResourceProviderDescriptor`` carries the provider identity plus the
mandatory ``reconcile_support`` capability declaration.  The id/display_name/
version validation rules are the same as ``work_core.registry.
ProviderDescriptor`` (component-id regex, non-blank display name/version) but
are re-declared here without the ``work_core`` import chain, because
``work_core/__init__`` reaches ``registry.py`` which imports
``resource_contracts`` — a chain the public facade must never pull in.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .enums import ReconcileSupport
from .errors import CoreDTOError, InvalidProviderIdError

_COMPONENT_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_CONTRACT_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*@[1-9][0-9]*$")


def validate_component_id(value: object, *, kind: str) -> str:
    if not isinstance(value, str) or not _COMPONENT_ID.fullmatch(value):
        raise InvalidProviderIdError(f"invalid {kind} id: {value!r}")
    return value


def validate_contract_id(value: object) -> str:
    if not isinstance(value, str) or not _CONTRACT_ID.fullmatch(value):
        raise CoreDTOError(
            "resource contract must declare a versioned contract_id like "
            f"vendor.name@1, got {value!r}"
        )
    return value


@dataclass(frozen=True)
class ResourceProviderDescriptor:
    """Self-declaration of one ResourceProvider, capability included.

    ``reconcile_support`` is never inferred: a provider that cannot
    reconcile must say so, and callers asking it anyway get the typed
    ``ReconcileUnsupportedError``.
    """

    id: str
    display_name: str
    version: str
    reconcile_support: ReconcileSupport

    def __post_init__(self) -> None:
        validate_component_id(self.id, kind="provider")
        for name, value in (("display_name", self.display_name),
                            ("version", self.version)):
            if not isinstance(value, str) or not value.strip():
                raise CoreDTOError(f"provider descriptor {name} is required")
        if not isinstance(self.reconcile_support, ReconcileSupport):
            raise CoreDTOError(
                "reconcile_support must be a ReconcileSupport member, got "
                f"{self.reconcile_support!r}"
            )
