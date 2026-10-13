"""Material provider declarations and their local identity invariants.

These declarations carry no registry, provider instance or execution authority.
Publication, pins and effects remain with the existing Units material owners.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re


class MaterialDeclarationError(RuntimeError, ValueError):
    """A material provider declaration violates a local invariant."""


class MaterialProviderIdError(MaterialDeclarationError):
    """A provider identity violates the persisted component-id syntax."""


class ReconcileSupport(str, Enum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"


_COMPONENT_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_CONTRACT_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*@[1-9][0-9]*$")


def validate_component_id(value: object, *, kind: str) -> str:
    if not isinstance(value, str) or not _COMPONENT_ID.fullmatch(value):
        raise MaterialProviderIdError(f"invalid {kind} id: {value!r}")
    return value


def validate_contract_id(value: object) -> str:
    if not isinstance(value, str) or not _CONTRACT_ID.fullmatch(value):
        raise MaterialDeclarationError(
            "resource contract must declare a versioned contract_id like "
            f"vendor.name@1, got {value!r}"
        )
    return value


@dataclass(frozen=True)
class ResourceProviderDescriptor:
    id: str
    display_name: str
    version: str
    reconcile_support: ReconcileSupport

    def __post_init__(self) -> None:
        validate_component_id(self.id, kind="provider")
        for name, value in (("display_name", self.display_name),
                            ("version", self.version)):
            if not isinstance(value, str) or not value.strip():
                raise MaterialDeclarationError(f"provider descriptor {name} is required")
        if not isinstance(self.reconcile_support, ReconcileSupport):
            raise MaterialDeclarationError(
                "reconcile_support must be a ReconcileSupport member, got "
                f"{self.reconcile_support!r}"
            )


__all__ = ["ResourceProviderDescriptor", "ReconcileSupport",
           "MaterialDeclarationError", "MaterialProviderIdError",
           "validate_component_id", "validate_contract_id"]
