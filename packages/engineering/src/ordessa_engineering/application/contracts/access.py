"""Application access ports: material/resource/capability reads and blob capture.

The adapter's ``MaterialBudget`` implements ``MaterialAccessPort`` against the
**same** original transaction/connection/scope/readset authority. The application
consumes these to coordinate reads; it must never pre-read here and reuse the
bytes across a different transaction. Only the methods the coordination actually
needs are declared.
"""
from __future__ import annotations

import hashlib

from typing import Protocol

from ...domain.artifacts.codec import encode_revision
from ...domain.changes.codec import encode_proposal
from ...domain.common.models.values import Digest
from ...domain.common.models.refs import BlobRef
from ...methods.definitions.models import CompilationCapabilities

__all__ = ['MaterialAccessPort', 'revision_validation_key', 'proposal_validation_key',
           'ResourceContentReader', 'CapabilityCatalogReader', 'BlobStorePort']


class MaterialAccessPort(Protocol):
    def reserve(self, refs) -> None: ...
    def read(self, ref) -> bytes: ...
    def method(self, ref): ...
    @property
    def selectors(self): ...
    def mark_validated(self, key) -> None: ...
    def is_validated(self, key) -> bool: ...
    def bind_validated_result(self, key, result) -> None: ...
    def validated_result(self, key): ...


def revision_validation_key(revision):
    """Exact validation key for one revision operation.

    Composition: ``('artifact-revision', scope.realm_id, scope.project_id,
    artifact_id, revision_id, sha256(canonical encode_revision(revision)))``.

    The **canonical content digest** is part of the key, so keeping the same
    ``revision_id`` while changing payload/digest/ref changes the key and the
    marker no longer matches; the scope is part of the key, so the same content in
    a different scope/operation does not match. The key lives on a per-operation
    budget instance, which binds the UoW/readset.

    This is **process-internal coordination against misuse**, not a security
    permit boundary: an external entry never receives the internal budget of an
    owner, so it cannot self-issue a marker; the repository re-checks the actual
    canonical content/immutable refs against the marker at save (no TOCTOU).
    """
    encoded = encode_revision(revision)
    scope = revision.scope
    return ('artifact-revision', scope.realm_id, scope.project_id,
            revision.artifact_id, revision.revision_id, hashlib.sha256(encoded).hexdigest())


def proposal_validation_key(record):
    """Exact validation key for one proposal-create operation.

    Composition: ``('proposal', scope.realm_id, scope.project_id, proposal_id,
    change_id, sha256(canonical encode_proposal(record)))``. Like
    :func:`revision_validation_key` it binds the canonical content and scope and
    lives on a per-operation budget instance (the UoW/readset binding). It is a
    trusted in-process coordination marker against misuse, **not** an
    unforgeable security token: an external caller never receives the owner's
    internal budget, and the repository re-checks the marker before writing.
    """
    scope = record.scope
    return ('proposal', scope.realm_id, scope.project_id, record.proposal_id,
            record.change_id, hashlib.sha256(encode_proposal(record)).hexdigest())


class ResourceContentReader(Protocol):
    def read_blob(self, ref: BlobRef) -> bytes: ...


class CapabilityCatalogReader(Protocol):
    """Injected by trusted application composition, never by method resources.

    The production adapter must read the existing registered owner catalog.
    Descriptor DTO fields or warning flags alone do not prove that origin.
    No production adapter exists yet; callers without this port fail closed.
    """

    def read_current(self) -> CompilationCapabilities: ...


class BlobStorePort(Protocol):
    """Verified byte capture outside business transactions, same authority."""
    authority_id: str
    def put_verified(self, raw_bytes: bytes, expected_digest: Digest, media_type: str) -> BlobRef: ...
    def read_verified(self, ref: BlobRef) -> bytes: ...
