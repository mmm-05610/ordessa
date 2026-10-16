"""Adapter-side per-resolution material access (budget / blob reads / CAS).

This module keeps only transaction access on the caller's original connection.
The source/selector/content closure rules live in
``ordessa_engineering.application.usecases.material_closure`` (coordinating reads
through the declared ``MaterialAccessPort``) with their pure rules owned by
``domain`` / ``methods``. No business acceptance decision is made here.
"""
from __future__ import annotations

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.common.mechanisms.selection import (SelectorChecks)
from ordessa_engineering.domain.common.models.refs import (BlobRef)
from ordessa_engineering.domain.common.models.values import (Digest)
from ordessa_engineering.domain.common.outcomes.diagnostics import (ReferenceError)
from ordessa_engineering.methods.definitions.errors import MethodFailure
from ordessa_engineering.methods.definitions.models import MethodRef as SnapshotRef
from .blob_bytes import BlobBytesError, read_bytes, validate_ref
from .snapshot_store import load_snapshot

MAX_MATERIAL_BYTES = 64 * 1024 * 1024


def _deny(code):
    raise ApplicationError(code)


class MaterialBudget:
    """Private per-resolution/TX budget, not a new byte store or authority.

    Implements the application ``MaterialAccessPort``: every read happens on the
    caller's own connection/scope; nothing is retained for cross-transaction reuse.
    """
    def __init__(self, access):
        self.access = access
        self.total = 0
        self.reserved = set()
        self.validated = set()
        self.validated_results = {}
        self.bodies = {}
        self.methods = {}
        self.snapshot_digests = set()
        self.record_keys = set()
        self.proposals = {}
        self.revisions = {}
        self.proposal_rows = {}
        self.selectors = SelectorChecks()

    def mark_validated(self, key):
        self.validated.add(key)

    def is_validated(self, key):
        return key in self.validated

    def bind_validated_result(self, key, result):
        """Bind the validated result to the same per-operation key.

        The adapter write consumes this bound result; a caller cannot substitute
        or empty the value without a key mismatch.
        """
        self.validated_results[key] = result

    def validated_result(self, key):
        return self.validated_results.get(key)

    def record(self, key, raw):
        if key not in self.record_keys:
            self.total += len(raw)
            if self.total > MAX_MATERIAL_BYTES:
                _deny('MATERIAL_LIMIT')
            self.record_keys.add(key)

    def reserve(self, refs):
        for ref in refs:
            try:
                validate_ref(self.access.authority_id, ref)
            except (BlobBytesError, ReferenceError):
                _deny('MATERIAL_BLOB_INVALID')
            key = (ref.digest.hex, ref.byte_length)
            if key not in self.reserved:
                self.total += ref.byte_length
                if self.total > MAX_MATERIAL_BYTES:
                    _deny('MATERIAL_LIMIT')
                self.reserved.add(key)

    def read(self, ref):
        # Validate every locator even when identical bytes have been cached.
        self.reserve((ref,))
        key = (ref.digest.hex, ref.byte_length)
        if key not in self.bodies:
            try:
                self.bodies[key] = read_bytes(self.access, self.access.authority_id, ref)
            except BlobBytesError as exc:
                _deny('MATERIAL_BLOB_' + exc.code)
        return self.bodies[key]

    def method(self, ref):
        if ref not in self.methods:
            converted = SnapshotRef(ref.method_id, ref.release_version,
                                    ref.schema_version, ref.snapshot_digest.hex)
            def budget(snapshot):
                # Metadata is bounded before any source body is read.
                refs = (snapshot.manifest_ref,) + tuple(r.blob_ref for r in snapshot.resources)
                from .snapshot_codec import encode_snapshot
                if snapshot.snapshot_digest not in self.snapshot_digests:
                    self.total += len(encode_snapshot(snapshot))
                    if self.total > MAX_MATERIAL_BYTES:
                        _deny('MATERIAL_LIMIT')
                    self.snapshot_digests.add(snapshot.snapshot_digest)
                self.reserve(tuple(BlobRef(Digest('sha256', r.digest), r.byte_length,
                                           r.media_type, r.storage_object_id) for r in refs))
            try:
                self.methods[ref] = load_snapshot(self.access, self.access.authority_id,
                                                 converted, budget=budget)
            except MethodFailure as exc:
                _deny('MATERIAL_METHOD_' + exc.error.code)
        return self.methods[ref]
