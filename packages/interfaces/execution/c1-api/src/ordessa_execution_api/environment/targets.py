"""Canonical fact targets and the single-writer authority key (025 V4 §14.1, E3 §3).

Frozen rules:

* ``CanonicalFactTarget`` is the ONLY slot key an authority may be registered
  under: realm + identity namespace + stable entity id. Target *schemas*,
  contract majors, provider instances, window/socket ids are transport
  representations and never part of the authority identity.
* ``AuthorityKey`` pairs the authority kind (the semantic name of the existing
  factDomainId) with the canonical target. Registering a second writer for the
  same key — via a different schema version, a fresh namespace alias, or a new
  provider instance — is an ``AuthorityConflictError`` at the registration
  boundary, unless a trusted equivalence mapping normalized both to the same
  canonical target first (which is exactly what ``AuthorityRegistration``
  records).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping

_REALM = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_NAMESPACE = re.compile(r"^[a-z][a-z0-9._-]{0,95}$")
_ENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$")
_KIND = re.compile(r"^[a-z][a-z0-9.-]{0,63}$")


@dataclass(frozen=True)
class CanonicalFactTarget:
    """Normalized fact target: {realm, identityNamespace, stableEntityId}."""

    realm: str
    identity_namespace: str
    stable_entity_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.realm, str) or not _REALM.match(self.realm):
            raise ValueError("CanonicalFactTarget.realm is malformed")
        if not isinstance(self.identity_namespace, str) or not _NAMESPACE.match(
            self.identity_namespace
        ):
            raise ValueError("CanonicalFactTarget.identity_namespace is malformed")
        if not isinstance(self.stable_entity_id, str) or not _ENTITY.match(
            self.stable_entity_id
        ):
            raise ValueError("CanonicalFactTarget.stable_entity_id is malformed")


@dataclass(frozen=True)
class AuthorityKey:
    """The single-writer slot: authorityKind + canonical target."""

    authority_kind: str
    target: CanonicalFactTarget

    def __post_init__(self) -> None:
        if not isinstance(self.authority_kind, str) or not _KIND.match(self.authority_kind):
            raise ValueError("AuthorityKey.authority_kind is malformed")


@dataclass(frozen=True)
class AuthorityRegistration:
    """What a trusted domain hands the platform when it claims a slot.

    ``normalized_from`` records the schema versions that normalize to the same
    canonical target (v1/v2 of one workspace fact produce the same
    stableEntityId). Registering a second writer without a trusted mapping is
    the C95-2/execution-detail §2 counterexample and must be refused.
    """

    key: AuthorityKey
    declaring_owner_domain: str
    target_schema_id: str
    schema_major: int
    normalized_from: tuple[str, ...] = ()
    alias_bindings: Mapping[str, str] = field(default_factory=dict, compare=True)

    def __post_init__(self) -> None:
        _ = AuthorityKey(self.key.authority_kind, self.key.target)  # validate
        if not isinstance(self.declaring_owner_domain, str) or not _NAMESPACE.match(
            self.declaring_owner_domain
        ):
            raise ValueError("AuthorityRegistration.declaring_owner_domain is malformed")
        if not isinstance(self.target_schema_id, str) or not self.target_schema_id:
            raise ValueError("AuthorityRegistration.target_schema_id is required")
        if type(self.schema_major) is not int or self.schema_major < 1:
            raise ValueError("AuthorityRegistration.schema_major must be >= 1")
