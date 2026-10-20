"""Dispatch continuation value and codec: closed shape, no binding byte change.

Pure domain only: no I/O, no execution or application import. The dispatch
binding samples below were captured from the unmodified v1/v2 codec before this
segment existed; they pin byte compatibility word for word.
"""
import hashlib
import json

import pytest

from ordessa_engineering.domain.changes.dispatch import (
    CONTINUATION_CONTRACT, CONTINUATION_SCHEMA_VERSION, DispatchContinuation,
    DispatchOriginRef, package_ref_projection, DispatchBinding,
)
from ordessa_engineering.domain.changes.dispatch_codec import (
    decode_continuation, decode_dispatch, encode_continuation, encode_dispatch,
)
from ordessa_engineering.domain.approvals.refs import ApprovalRef
from ordessa_engineering.domain.common.models.identity import Scope
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from ordessa_engineering.domain.packages.refs import ImplementationPackageRef
from ordessa_infrastructure.encoding import canonical_bytes

SCOPE = Scope('realm-a', 'project-a')
OTHER_SCOPE = Scope('realm-a', 'project-b')

# Captured before this segment: canonical bytes of a v1 and a v2 binding.
BINDING_V1_BYTES = (
    b'{"action_instances":[["edit_repository","inst-1"],["run_checks","inst-2"]],'
    b'"approval_ref":{"approval_id":"approval-a","grant_digest":{"algorithm":"sha256",'
    b'"hex":"dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"},'
    b'"kind":"approval","project_id":"project-a","realm_id":"realm-a"},"attempt":1,'
    b'"control_version":1,"digest":{"algorithm":"sha256",'
    b'"hex":"f963bef91c82e46ab08cbfac8f10a4f778f827e4b5acdb53f5f6655f53410289"},'
    b'"execution_operation_ref":"op-a","expected_query_digest":"q-a","fence":1,'
    b'"intent_digest":{"algorithm":"sha256",'
    b'"hex":"eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"},'
    b'"package_ref":{"digest":{"algorithm":"sha256",'
    b'"hex":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},'
    b'"kind":"implementation_package","package_id":"package-a","project_id":"project-a",'
    b'"realm_id":"realm-a"},"prompt_input_digest":{"algorithm":"sha256",'
    b'"hex":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"},'
    b'"prompt_ref":{"byte_length":10,"digest":{"algorithm":"sha256",'
    b'"hex":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"},'
    b'"media_type":"application/json","storage_object_id":"blob-a"},'
    b'"required_results":["implementation_report"],"run_id":"run-a",'
    b'"scope":{"project_id":"project-a","realm_id":"realm-a"},"step_id":"implement",'
    b'"unit_ref_bytes":{"environmentNamespace":"env-a","ownerProviderRef":{},'
    b'"sourceRevision":"rev-1","unitId":"unit-a"}}')

BINDING_V2_BYTES = (
    b'{"action_instances":[["edit_repository","inst-1"],["run_checks","inst-2"]],'
    b'"approval_ref":{"approval_id":"approval-a","grant_digest":{"algorithm":"sha256",'
    b'"hex":"dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"},'
    b'"kind":"approval","project_id":"project-a","realm_id":"realm-a"},"attempt":1,'
    b'"binding_version":2,"control_version":1,"digest":{"algorithm":"sha256",'
    b'"hex":"b56d201e1c23e6a218f4ec4557a40ddfde99b26d4a752dab8df45c7bfb31baf1"},'
    b'"execution_operation_ref":"op-a","expected_query_digest":"q-a","fence":1,'
    b'"intent_digest":{"algorithm":"sha256",'
    b'"hex":"eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"},'
    b'"package_ref":{"digest":{"algorithm":"sha256",'
    b'"hex":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},'
    b'"kind":"implementation_package","package_id":"package-a","project_id":"project-a",'
    b'"realm_id":"realm-a"},"prompt_input_digest":{"algorithm":"sha256",'
    b'"hex":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"},'
    b'"prompt_ref":{"byte_length":10,"digest":{"algorithm":"sha256",'
    b'"hex":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"},'
    b'"media_type":"application/json","storage_object_id":"blob-a"},'
    b'"required_results":["implementation_report"],"run_id":"run-a",'
    b'"scope":{"project_id":"project-a","realm_id":"realm-a"},"step_id":"implement",'
    b'"subject":{"subject_kind":"frozen_package","subject_ref":{"digest":'
    b'{"algorithm":"sha256",'
    b'"hex":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},'
    b'"kind":"implementation_package","package_id":"package-a","project_id":"project-a",'
    b'"realm_id":"realm-a"}},"unit_ref_bytes":{"environmentNamespace":"env-a",'
    b'"ownerProviderRef":{},"sourceRevision":"rev-1","unitId":"unit-a"},'
    b'"work":{"action_id":"incremental.implement-package","dispatch_key":"w1:work-a",'
    b'"step_id":"implement","work_id":"work-a"}}')


def digest(text):
    return Digest('sha256', hashlib.sha256(text).hexdigest())


def blob(text):
    return BlobRef(digest(text), 12, 'application/json',
                   'storage-' + hashlib.sha256(text).hexdigest()[:12])


def origin(*, scope=SCOPE, attempt=1, execution_operation_ref='op-a',
           bytes_digest=None, record_digest=None, dispatch_version=2, acp_revision=2):
    return DispatchOriginRef(
        scope=scope, dispatch_key='w1:work-a', step_id='implement', attempt=attempt,
        execution_operation_ref=execution_operation_ref,
        binding_bytes_digest=bytes_digest or digest(b'origin-bytes'),
        binding_record_digest=record_digest or digest(b'origin-record'),
        expected_dispatch_version=dispatch_version, expected_acp_revision=acp_revision)


def continuation(**overrides):
    values = dict(
        origin=origin(), reservation_origin=origin(),
        causal_operation_id='work-continuation-a',
        failure_evidence_ref=blob(b'diagnostic'),
        acp_observation_ref=blob(b'observation'),
        acp_revision=2, stop_proof_ref='stop-proof-a', release_proof_ref='release-proof-a',
        semantic_prompt_digest=digest(b'prompt'), 
        successor_binding_record_digest=digest(b'successor'))
    values.update(overrides)
    return DispatchContinuation(**values)


# --------------------------------------------------------------- value layer

def test_contract_and_schema_are_fixed():
    assert CONTINUATION_CONTRACT == 'engineering.dispatch-continuation/1'
    assert CONTINUATION_SCHEMA_VERSION == 1
    value = continuation()
    assert value.schema_version == 1


def test_projection_is_closed_and_digest_is_sealed():
    value = continuation()
    projected = value.projection()
    assert set(projected) == {
        'schema_version', 'origin', 'reservation_origin', 'causal_operation_id',
        'failure_evidence_ref', 'acp_observation_ref', 'acp_revision',
        'stop_proof_ref', 'release_proof_ref', 'semantic_prompt_digest',
        'successor_binding_record_digest'}
    assert 'digest' not in projected
    assert type(value.digest) is Digest
    changed = continuation(acp_revision=3)
    assert changed.digest != value.digest
    assert continuation().digest == value.digest  # deterministic


def test_two_binding_digests_are_kept_apart_not_conflated():
    forward = continuation()
    swapped = continuation(
        origin=origin(bytes_digest=digest(b'origin-record'),
                      record_digest=digest(b'origin-bytes')),
        reservation_origin=origin(bytes_digest=digest(b'origin-record'),
                                  record_digest=digest(b'origin-bytes')))
    assert forward.origin.binding_bytes_digest != forward.origin.binding_record_digest
    assert forward.digest != swapped.digest
    assert encode_continuation(forward) != encode_continuation(swapped)
    projected = forward.projection()['origin']
    assert projected['binding_bytes_digest'] == {
        'algorithm': 'sha256', 'hex': forward.origin.binding_bytes_digest.hex}
    assert projected['binding_record_digest'] == {
        'algorithm': 'sha256', 'hex': forward.origin.binding_record_digest.hex}


def test_cross_scope_continuation_is_refused():
    with pytest.raises(ReferenceError, match='INVALID_DISPATCH_CONTINUATION'):
        continuation(origin=origin(scope=OTHER_SCOPE))


@pytest.mark.parametrize('field', ['attempt', 'expected_dispatch_version', 'expected_acp_revision'])
@pytest.mark.parametrize('value', [0, -1, True, 1.0, '1'])
def test_origin_versions_are_strict_positive_ints(field, value):
    kwargs = {'attempt': 1, 'dispatch_version': 2, 'acp_revision': 2}
    kwargs[{'attempt': 'attempt', 'expected_dispatch_version': 'dispatch_version',
            'expected_acp_revision': 'acp_revision'}[field]] = value
    with pytest.raises(ReferenceError, match='INVALID_DISPATCH_CONTINUATION'):
        origin(**kwargs)


@pytest.mark.parametrize('value', [0, True, 1.0, '2'])
def test_acp_revision_is_a_strict_positive_int(value):
    with pytest.raises(ReferenceError, match='INVALID_DISPATCH_CONTINUATION'):
        continuation(acp_revision=value)


def test_origin_digests_must_be_digests():
    with pytest.raises(ReferenceError, match='INVALID_DISPATCH_CONTINUATION'):
        origin(bytes_digest='sha256:' + 'a' * 64)


# ------------------------------------------------------------------- codec

def test_roundtrip_is_canonical_and_deterministic():
    value = continuation()
    raw = encode_continuation(value)
    assert raw == canonical_bytes(json.loads(raw))
    assert decode_continuation(raw) == value
    assert encode_continuation(decode_continuation(raw)) == raw


def test_unknown_continuation_version_is_refused():
    raw = json.loads(encode_continuation(continuation()))
    # A float version cannot even be canonicalised at the byte boundary, so
    # only JSON-native wrong versions are exercised here.
    for version in (2, 0, True):
        forged = canonical_bytes(dict(raw, schema_version=version))
        with pytest.raises(ReferenceError, match='INVALID_DISPATCH_CONTINUATION'):
            decode_continuation(forged)


def test_unknown_fields_are_refused_at_each_level():
    raw = json.loads(encode_continuation(continuation()))
    with pytest.raises(ReferenceError, match='INVALID_DISPATCH_CONTINUATION'):
        decode_continuation(canonical_bytes(dict(raw, continuation_extra=True)))
    nested = dict(raw, origin=dict(raw['origin'], note='not part of the contract'))
    with pytest.raises(ReferenceError, match='INVALID_DISPATCH_CONTINUATION'):
        decode_continuation(canonical_bytes(nested))


def test_bad_digest_format_is_refused():
    raw = json.loads(encode_continuation(continuation()))
    short = dict(raw, semantic_prompt_digest={'algorithm': 'sha256', 'hex': 'a' * 40})
    with pytest.raises(ReferenceError):
        decode_continuation(canonical_bytes(short))
    wrong_algorithm = dict(raw, semantic_prompt_digest={'algorithm': 'md5', 'hex': 'a' * 64})
    with pytest.raises(ReferenceError):
        decode_continuation(canonical_bytes(wrong_algorithm))


def test_tampered_digest_or_payload_is_refused():
    raw = json.loads(encode_continuation(continuation()))
    forged = dict(raw, digest={'algorithm': 'sha256', 'hex': 'f' * 64})
    with pytest.raises(ReferenceError, match='INVALID_DISPATCH_CONTINUATION'):
        decode_continuation(canonical_bytes(forged))
    changed = dict(raw, causal_operation_id='work-continuation-b')
    with pytest.raises(ReferenceError, match='INVALID_DISPATCH_CONTINUATION'):
        decode_continuation(canonical_bytes(changed))


def test_noncanonical_bytes_are_refused():
    raw = encode_continuation(continuation())
    with pytest.raises(ReferenceError):
        decode_continuation(b' ' + raw)


# ------------------------------------------------- dispatcher byte stability

@pytest.mark.parametrize('raw,record_hex', [
    (BINDING_V1_BYTES, 'f963bef91c82e46ab08cbfac8f10a4f778f827e4b5acdb53f5f6655f53410289'),
    (BINDING_V2_BYTES, 'b56d201e1c23e6a218f4ec4557a40ddfde99b26d4a752dab8df45c7bfb31baf1'),
])
def test_dispatch_binding_samples_stay_byte_identical(raw, record_hex):
    binding = decode_dispatch(raw)
    assert binding.digest.hex == record_hex
    assert encode_dispatch(binding) == raw
    assert encode_dispatch(decode_dispatch(raw)) == raw


# ------------------------------------------------------------ domain purity

def test_domain_continuation_module_has_no_io_or_outer_layer_imports():
    from pathlib import Path
    base = Path(__file__).resolve().parents[2] / 'src/ordessa_engineering/domain/changes'
    for name in ('dispatch.py', 'dispatch_codec.py'):
        text = (base / name).read_text()
        for forbidden in ('import sqlite3', 'from ...application', 'from ...adapters',
                          'from ...orchestration', 'import ordessa_server',
                          'from ordessa_server', 'from ordessa_execution'):
            assert forbidden not in text, (name, forbidden)
