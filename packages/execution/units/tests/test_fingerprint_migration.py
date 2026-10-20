"""Historical request-input identity and cold spent/tombstone guarantees."""
import pytest
from ordessa_infrastructure.identifiers import RequestKey
from ordessa_units.errors import UnitComparisonUnavailable
from ordessa_units.admission.fingerprint import ProtectedFingerprintHmac
from ordessa_units.persistence.sqlite.store import SqliteUnitStore, KeyConflictError


def test_original_fingerprint_vector_and_principal_separation():
    request = RequestKey('env', 'principal', 'original-request')
    fingerprint = ProtectedFingerprintHmac({'fixture': b'TEMPORARY_CONTROLLED_KEY'}, active_key_id='fixture')
    # Literal captured from the original adapter before its retirement.
    original = fingerprint.fingerprint(request, 'original-surface', 'fixed-content')
    assert original == 'ca0dd666018d28ba6ad02f485631ef742c216122b36570e51e7a7b2f31142836'
    assert fingerprint.verify('fixture', original, request, 'original-surface', 'fixed-content') is True
    assert fingerprint.verify('fixture', original, RequestKey('env', 'other', 'original-request'),
        'original-surface', 'fixed-content') is False


def test_rotation_and_cold_tombstone_never_make_original_request_dispatchable(tmp_path):
    path = tmp_path / 'original.sqlite'
    store = SqliteUnitStore(path)
    request = RequestKey('env', 'principal', 'original-request')
    fingerprint = ProtectedFingerprintHmac({'original': b'TEMPORARY_ORIGINAL_KEY'},
        active_key_id='original', tombstone_check=store.has_key_tombstone)
    digest = fingerprint.fingerprint(request, 'original-surface', 'fixed-content')
    assert store.reserve_request(request, digest) is True
    fingerprint.rotate('rotated', b'TEMPORARY_ROTATED_KEY')
    store.record_key_tombstone('original')
    store.close()
    cold = SqliteUnitStore(path)
    try:
        reader = ProtectedFingerprintHmac({'original': b'TEMPORARY_ORIGINAL_KEY',
            'rotated': b'TEMPORARY_ROTATED_KEY'}, active_key_id='rotated', tombstone_check=cold.has_key_tombstone)
        with pytest.raises(UnitComparisonUnavailable, match='retired'):
            reader.verify('original', digest, request, 'original-surface', 'fixed-content')
        new_digest = reader.fingerprint(request, 'original-surface', 'fixed-content')
        with pytest.raises(KeyConflictError):
            cold.reserve_request(request, new_digest)
        assert cold.read_request(request)['digest'] == digest
        assert cold.has_key_tombstone('original') is True
    finally:
        cold.close()
