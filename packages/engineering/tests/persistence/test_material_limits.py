"""Independent denial evidence for selector work and combined material budgets."""
from dataclasses import replace
import hashlib

import pytest

from ordessa_engineering.adapters.persistence.sqlite import material_validation
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.adapters.persistence.sqlite.snapshot_codec import encode_snapshot
from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import verify_snapshot_source
from ordessa_engineering.domain.common.models.selection import (ContentSelector)
from ordessa_engineering.domain.common.mechanisms.selection import (SelectorChecks)
from ordessa_engineering.domain.common.models.values import (Digest)
from ordessa_engineering.domain.common.outcomes.diagnostics import (ReferenceError)
from ordessa_engineering.methods.definitions.errors import MethodFailure
from test_material_repository import _artifact, _append, _library, _revision
from test_method_content import _publish_document_method


def test_selector_work_is_cached_but_cached_expected_digest_is_never_trusted():
    raw = b'A' * (16 * 1024 * 1024)
    digest = Digest('sha256', hashlib.sha256(raw).hexdigest())
    whole = ContentSelector('whole_capture')
    checks = SelectorChecks()
    for _ in range(100):
        assert checks.check(raw, whole, digest) == raw
    with pytest.raises(ReferenceError) as wrong:
        checks.check(raw, whole, Digest('sha256', '0' * 64))
    assert wrong.value.code == 'STATEMENT_DIGEST_MISMATCH'
    checks.check(raw, ContentSelector('byte_range', start=0, end=len(raw)-1))
    with pytest.raises(ReferenceError) as limited:
        checks.check(raw, ContentSelector('byte_range', start=1, end=len(raw)))
    assert limited.value.code == 'SELECTOR_WORK_LIMIT'


def test_published_snapshot_and_source_bytes_share_one_budget(tmp_path, monkeypatch):
    library = _library(tmp_path / 'combined-budget.sqlite')
    try:
        method, snapshot = _publish_document_method(library, tmp_path / 'method')
        canonical_size = len(encode_snapshot(snapshot))
        source_size = snapshot.manifest_ref.byte_length + sum(r.byte_length for r in snapshot.resources)
        # Both individual components fit; their combination must refuse before
        # source body verification. Use the real published DTO and original UoW.
        monkeypatch.setattr(material_validation, 'MAX_MATERIAL_BYTES', canonical_size + source_size - 1)
        _artifact(library)
        with pytest.raises(material_validation.ApplicationError) as refused:
            _append(library, _revision(method_refs=(method,)))
        assert refused.value.code == 'MATERIAL_LIMIT'
        assert library._connection.execute('SELECT COUNT(*) FROM eng_artifact_revisions').fetchone() == (0,)
    finally:
        library.close()


def test_actual_captured_manifest_fault_uses_finite_source_error(tmp_path):
    library = _library(tmp_path / 'finite-source-error.sqlite')
    try:
        _method, snapshot = _publish_document_method(library, tmp_path / 'method')
        import json
        from ordessa_engineering.methods.definitions.models import BlobRef as SnapshotBlobRef
        original = (tmp_path / 'method' / 'method.yaml').read_bytes()
        value = json.loads(original)
        del value['resources'][0]['id']
        raw = json.dumps(value, separators=(',', ':')).encode()
        ref = SQLiteBlobStore(library).put_verified(raw, Digest('sha256', hashlib.sha256(raw).hexdigest()), 'application/yaml')
        captured = SnapshotBlobRef(ref.digest.hex, ref.byte_length, ref.media_type, ref.storage_object_id)
        # Exercise the unique source helper with actual persisted bytes; this
        # does not claim a corrupt snapshot could pass its outer codec.
        with library.transaction() as connection:
            with pytest.raises(MethodFailure) as failed:
                verify_snapshot_source(
                    connection, library.library_id,
                    replace(snapshot, source_bundle=replace(snapshot.source_bundle, manifest_ref=captured)),
                )
            assert failed.value.error.code == 'SNAPSHOT_SOURCE_INVALID'
    finally:
        library.close()
