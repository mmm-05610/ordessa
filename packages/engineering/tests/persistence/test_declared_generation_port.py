"""The declared generation port on a real schema-17 library.

The Unit transport, blobs, unit resolver and grant are labelled test doubles; the
library, the UoW gate, the package codec and the package store are the real ones.
"""
import hashlib
import pathlib
import sqlite3
from contextlib import contextmanager
from types import SimpleNamespace
from dataclasses import asdict

import pytest

from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.orchestration.steps.declared_generation_port import (
    DeclaredGenerationPort, _prompt)
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import (
    EngineeringLibrary)
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.adapters.persistence.sqlite.dispatch_schema import WORK_DISPATCH_DDL
from ordessa_engineering.domain.artifacts.method_binding import (
    ExactMethodResourceRef, MethodRef)
from ordessa_engineering.domain.artifacts.provenance import (
    SourceLocator, SourceRef, VersionCapture)
from ordessa_engineering.domain.changes.refs import ProposalRef
from ordessa_engineering.domain.reviews.refs import ReviewRef
from ordessa_engineering.domain.common.models.identity import ActorRef, Scope
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.packages.codec import package_payload_projection
from ordessa_engineering.domain.packages.models import (
    ImplementationPackage, PackageDocument, PreparedPackagePayload)

SCOPE = Scope('gen-realm', 'gen-project')
ACTOR = ActorRef('actor-1', 'agent', 'issuer-1')


def _source(name, version, raw):
    # the construction the repository's own chain tests use for a real source
    return SourceRef(name, 'document',
                     SourceLocator('document', provider='project-files', document_id=name),
                     VersionCapture(version, Digest('sha256', hashlib.sha256(raw).hexdigest())),
                     '2026-06-01T00:00:00.000000Z', ACTOR, 'text/markdown', len(raw))


def _source_at(locator_document, version, raw):
    """One version of the same locator: baseline and candidate share a locator."""
    return _source(locator_document, version, raw)


def _payload():
    # the contract requires one locator with two distinct content identities
    baseline = _source_at('repo-file', 'v1', b'base')
    candidate = _source_at('repo-file', 'v2', b'cand')
    documents = (PackageDocument('spec', _source('spec-doc', 'v1', b'spec')),
                 PackageDocument('plan', _source('plan-doc', 'v1', b'plan')))
    # the real reference types the payload contract requires
    change = ProposalRef(SCOPE.realm_id, SCOPE.project_id, 'change-1', 'proposal-1',
                         Digest('sha256', 'a' * 64))
    review = ReviewRef(SCOPE.realm_id, SCOPE.project_id, 'review-1', Digest('sha256', 'b' * 64))
    method = MethodRef('ordessa.incremental-engineering', '2.7.2', 1, Digest('sha256', 'c' * 64))
    resource = ExactMethodResourceRef(method, 'templates/spec-kit/spec.md',
                                      Digest('sha256', 'd' * 64), 'spec-kit-spec')
    return PreparedPackagePayload(baseline, candidate, change, (review,), method,
                                  (resource,), documents)


def _captured_projection(package_id='package-1'):
    payload = _payload()
    return canonical_bytes({'package_id': package_id, 'created_at': '2026-06-01T00:00:00.000000Z',
                            'created_by': {'actor_id': ACTOR.actor_id,
                                           'actor_kind': ACTOR.actor_kind,
                                           'issuer': ACTOR.issuer},
                            'payload': package_payload_projection(payload)})


class _Blobs:
    """Labelled blob store double: holds exactly the bytes handed to it."""
    def __init__(self, captured=b''):
        self.captured = captured
        self.puts = []

    def put_verified(self, raw_bytes, expected_digest, media_type):
        self.puts.append((raw_bytes, expected_digest))
        return BlobRef(expected_digest, len(raw_bytes), media_type, 'prompt-object')

    def read_verified(self, ref):
        return self.captured


class _SourceMaterials:
    def __init__(self, factory, sources):
        self.factory = factory
        self.sources = sources
        self.reads = []

    def read(self, context, ref):
        self.reads.append(ref)
        return self.sources[(ref.source_id, ref.capture.upstream_version)]


class _Transport:
    """Labelled Unit-transport double: no network, records its sends."""
    def __init__(self, captured):
        self.sends = 0
        self.captured = captured

    def freeze_input(self, unit_ref, params):
        raw = canonical_bytes({'frozen': {'unit_ref': unit_ref, 'params': params}})
        return raw, Digest('sha256', hashlib.sha256(raw).hexdigest())

    def query_digest(self, unit_ref, operation_ref, prompt_digest):
        return 'q' * 64

    def guard_effect_handoff(self, context, binding, *, access, timeout=60):
        @contextmanager
        def _handoff():
            yield
        return _handoff()

    def send(self, binding, *, timeout=60):
        self.sends += 1

    def capture(self, binding):
        return SimpleNamespace(blob_ref=BlobRef(Digest('sha256', 'e' * 64), 10,
                                                'application/json', 'result-object'))


class _Grant:
    def __init__(self, ref, intent_digest):
        self.ref = ref
        self.control_version = 0
        self.intent = SimpleNamespace(not_before='2026-01-01T00:00:00Z',
                                      expires_at='2027-01-01T00:00:00Z',
                                      actions=('generate_package',), scope=SCOPE,
                                      targets=('proposal-1',), digest=intent_digest)


class _Approvals:
    def __init__(self, grant):
        self.grant = grant
        self.consumed = []

    def get_grant(self, ref):
        return self.grant

    def get_control(self, ref):
        return SimpleNamespace(state='active', version=0)

    def consume_action(self, ref, *, action, action_instance_id, target_digest, now):
        self.consumed.append(action)


def test_the_schema_17_gate_is_open_on_a_real_library(tmp_path):
    lib = EngineeringLibrary.create((tmp_path / 'gate17.sqlite').resolve(),
                                    library_id='gate-17', schema_version=17)
    try:
        with SQLiteUoWFactory(lib).begin(SCOPE, 'read') as uow:
            assert uow.implementation is not None
    finally:
        lib.close()


# --- the port itself, over the real schema-17 library ---------------------------

from ordessa_engineering.application.orchestration.steps import declared_generation_dispatch as mod
from ordessa_engineering.adapters.persistence.sqlite.dispatch_repository import (
    SQLiteWorkDispatchRepository)
from ordessa_engineering.adapters.persistence.sqlite.implementation_repository import (
    SQLiteImplementationRepository)
from ordessa_engineering.domain.approvals.refs import ApprovalRef
from ordessa_engineering.domain.changes.dispatch import DispatchBinding
from ordessa_engineering.domain.changes.dispatch_codec import encode_dispatch

WORK = 'work-1'
ACTION = 'incremental.prepare-packages'
STEP = 'draft'
KEY = 'w1:%s:%s:%s' % (WORK, ACTION, STEP)
INTENT = Digest('sha256', 'a' * 64)


class _Access:
    def __init__(self, connection, scope):
        self._connection = connection
        self.scope = scope

    def check_active(self):
        if not self._connection.in_transaction:
            raise ApplicationError('UOW_NOT_ACTIVE')

    def require_write(self):
        self.check_active()

    def require(self, context, capability):
        self.check_active()
        if capability != 'engineering.executions.dispatch':
            raise ApplicationError('CAPABILITY_NOT_BOUND')

    def execute(self, sql, parameters=()):
        return self._connection.execute(sql, parameters)


class _UowDouble:
    def __init__(self, connection, dispatch, approvals, scope, implementation):
        self._connection = connection
        self.dispatch = dispatch
        self.work_dispatch = dispatch
        self.authorization = approvals
        self.scope = scope
        self.implementation = implementation

    def commit(self):
        self._connection.commit()
        if not self._connection.in_transaction:
            self._connection.execute('BEGIN')

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def _library_with_work(tmp_path, name):
    path = (tmp_path / name).resolve()
    lib = EngineeringLibrary.create(path, library_id=name.replace('.', '-'),
                                    schema_version=17)
    connection = lib._connection
    if not connection.in_transaction:
        connection.execute('BEGIN')
    connection.execute(
        'INSERT INTO materials VALUES (?,?,?,?,?,?)',
        ('work-context', 'declarative-work:' + WORK, 1, 'f' * 64,
         canonical_bytes({'work_id': WORK,
                          'scope': {'realm_id': SCOPE.realm_id,
                                    'project_id': SCOPE.project_id},
                          'revision': 1}).decode('utf-8'), 0))
    return lib, connection


def _binding():
    return encode_dispatch(DispatchBinding(
        SCOPE, KEY, STEP, 1, 1, None,
        ApprovalRef(SCOPE.realm_id, SCOPE.project_id, 'grant-1', INTENT), INTENT, 0,
        (('generate_package', 'instance-1'),),
        canonical_bytes({'environmentNamespace': 'env', 'unitId': 'unit-1',
                         'ownerProviderRef': {'provider': 'local'},
                         'sourceRevision': 'rev-1'}),
        'operation-1', BlobRef(Digest('sha256', 'c' * 64), 10, 'application/json', 'prompt'),
        Digest('sha256', 'd' * 64), 'e' * 64, ('submission',), binding_version=2,
        work={'work_id': WORK, 'action_id': ACTION, 'step_id': STEP, 'dispatch_key': KEY},
        subject={'subject_kind': 'reviewed_change',
                 'subject_ref': {'reviewed_change_id': 'proposal-1'}}))


def _port(lib, connection, transport, captured):
    access = _Access(connection, SCOPE)
    approvals = _Approvals(_Grant(ApprovalRef(SCOPE.realm_id, SCOPE.project_id, 'grant-1',
                                              INTENT), INTENT))
    real_dispatch = SQLiteWorkDispatchRepository(access)
    real_packages = SQLiteImplementationRepository(access)

    class _Factory:
        def begin(self, scope, mode=None):
            if not connection.in_transaction:
                connection.execute('BEGIN')
            return _UowDouble(connection, real_dispatch, approvals, scope, real_packages)

    factory = _Factory()
    blobs = _Blobs(captured)
    source_materials = _SourceMaterials(factory, {('repo-file', 'v1'): b'base',
                                                   ('repo-file', 'v2'): b'cand'})
    mod.decode_approval_ref = lambda value: value
    return DeclaredGenerationPort(factory, access, blobs=blobs,
                                  execution=transport,
                                  dispatch=mod.DeclaredGenerationDispatch(
                                      factory, access, blobs=blobs,
                                      execution=transport,
                                      review_admission=object(), method_guard=object()),
                                  validation=lambda *_args: None,
                                  source_materials=source_materials,
                                  unit_ref_resolver=lambda context, binding, profile_ref: {
                                      'environmentNamespace': 'env', 'unitId': 'unit-1',
                                      'ownerProviderRef': {'provider': 'local'},
                                      'sourceRevision': 'rev-1'})


def _context():
    return SimpleNamespace(scope=SCOPE, received_at='2026-06-01T00:00:00.000000Z')


def _grant_argument():
    return {'approval_ref': ApprovalRef(SCOPE.realm_id, SCOPE.project_id, 'grant-1', INTENT),
            'targets': ('proposal-1',), 'reviewed_change_id': 'proposal-1',
            'intent_digest': INTENT}


def test_a_same_id_target_of_another_kind_or_version_is_not_authorized():
    """The negative case: a bare id, another kind, or another digest must not match."""
    from ordessa_engineering.application.orchestration.steps.declared_generation_dispatch import (
        _target_key)
    from ordessa_engineering.domain.changes.refs import ProposalRef
    from ordessa_engineering.domain.reviews.refs import ReviewRef

    pinned = ProposalRef(SCOPE.realm_id, SCOPE.project_id, 'change-1', 'proposal-1',
                         Digest('sha256', 'a' * 64))
    other_kind = ReviewRef(SCOPE.realm_id, SCOPE.project_id, 'proposal-1',
                           Digest('sha256', 'a' * 64))
    other_digest = ProposalRef(SCOPE.realm_id, SCOPE.project_id, 'change-1', 'proposal-1',
                               Digest('sha256', 'b' * 64))
    other_scope = ProposalRef('other-realm', SCOPE.project_id, 'change-1', 'proposal-1',
                              Digest('sha256', 'a' * 64))

    assert _target_key(pinned) != _target_key(other_kind)
    assert _target_key(pinned) != _target_key(other_digest)
    assert _target_key(pinned) != _target_key(other_scope)
    assert _target_key(pinned) != _target_key('proposal-1')      # a bare id proves nothing
    assert _target_key(pinned) == _target_key(pinned)

    wanted = {_target_key(pinned)}
    for decoy in (other_kind, other_digest, other_scope, 'proposal-1'):
        granted = {_target_key(decoy)}
        assert not wanted <= granted, decoy


def test_generation_input_is_one_native_acp_text_block_with_all_exact_materials():
    from ordessa_engineering.domain.changes.ref_codec import decode_proposal_ref
    from ordessa_engineering.domain.artifacts.provenance_codec import decode_source
    from ordessa_engineering.application.contracts.declared_generation import REQUIRED_MATERIALS

    payload = _payload()
    qualified = {
        "qualified_inputs": {
            "baseline": asdict(payload.baseline),
            "candidate": asdict(payload.candidate),
            "scope": asdict(SCOPE),
            "review": asdict(payload.review_refs[0]),
            "method": asdict(payload.method_ref),
        },
        "admitted": True,
        "verdict": "pass",
        "method_resource_refs": [asdict(payload.method_resource_refs[0])],
    }
    materials = {name: ("released:" + name).encode() for name in REQUIRED_MATERIALS}
    change = payload.change_ref
    params, baseline, candidate = _prompt(
        qualified, materials, change, payload.review_refs[0], payload.method_ref,
        payload.method_resource_refs, received_at="2026-06-01T00:00:00.000000Z",
        authenticated_actor=ACTOR.actor_id,
        source_texts={"baseline": {"source_ref": asdict(payload.baseline), "content": "base"},
                      "candidate": {"source_ref": asdict(payload.candidate), "content": "cand"}},
        review_material={"review_ref": asdict(payload.review_refs[0]),
                         "record": {"schema_version": 2},
                         "raw_response_ref": {"digest": {"algorithm": "sha256",
                                                           "hex": "a" * 64}},
                         "raw_response": "{}"})

    assert set(params) == {"prompt"}
    assert params["prompt"] == [{"type": "text", "text": params["prompt"][0]["text"]}]
    request = decode_json(params["prompt"][0]["text"].encode())
    assert request["pinned"]["baseline"] == qualified["qualified_inputs"]["baseline"]
    assert request["pinned"]["candidate"] == qualified["qualified_inputs"]["candidate"]
    assert request["pinned"]["change_ref"] == asdict(change)
    assert request["pinned"]["review_ref"] == asdict(payload.review_refs[0])
    assert request["pinned"]["method_ref"] == asdict(payload.method_ref)
    assert request["pinned"]["method_resource_refs"] == [
        asdict(ref) for ref in payload.method_resource_refs]
    assert request["released_materials"] == {
        name: raw.decode() for name, raw in materials.items()}
    assert request["source_documents"]["baseline"]["content"] == "base"
    assert request["source_documents"]["candidate"]["content"] == "cand"
    assert request["admitted_review"]["raw_response"] == "{}"
    assert baseline == decode_source(qualified["qualified_inputs"]["baseline"])
    assert candidate == decode_source(qualified["qualified_inputs"]["candidate"])


def test_generation_source_materials_are_digest_checked_before_unit_resolution(tmp_path):
    payload = _payload()
    lib, connection = _library_with_work(tmp_path, 'source-materials.sqlite')
    transport = _Transport(b'')
    try:
        port = _port(lib, connection, transport, b'')
        texts = port._source_texts(_context(), payload.baseline, payload.candidate)
        assert texts['baseline']['content'] == 'base'
        assert texts['candidate']['content'] == 'cand'
        assert len(port.source_materials.reads) == 2

        port.source_materials.sources[('repo-file', 'v1')] = b'wrong'
        with pytest.raises(ApplicationError, match='SOURCE_CONTENT_MISMATCH'):
            port._source_texts(_context(), payload.baseline, payload.candidate)
        assert transport.sends == 0
    finally:
        lib.close()


def test_native_summary_output_is_a_package_envelope_not_a_receipt_or_blob_ref():
    base = _payload()
    contents = {"spec": "# Spec\nCafé is UTF-8.\n",
                "plan": "# Plan\nFollow the admitted change.\n",
                "tasks": "# Tasks\n- [ ] Verify.\n"}
    envelope = {
        "contract_version": "ordessa.generated-package-documents/v1",
        "package_id": "package-generated",
        "document_contents": contents,
    }
    # The envelope contains only generated content; host code owns every pin.
    assert set(envelope) == {"contract_version", "package_id", "document_contents"}
    context = SimpleNamespace(
        scope=SCOPE, received_at="2026-06-01T00:00:00.000000Z", authenticated_actor=ACTOR)
    package, document_bytes = DeclaredGenerationPort._decode_output(
        canonical_bytes(envelope).decode(), context,
        change_ref=base.change_ref, review_ref=base.review_refs[0],
        method_ref=base.method_ref, method_resource_refs=base.method_resource_refs,
        baseline=base.baseline, candidate=base.candidate)

    assert type(package) is ImplementationPackage
    assert package.package_id == "package-generated"
    assert package.created_at == context.received_at
    assert package.created_by == ACTOR
    assert {document.role for document in package.payload.documents} == {"spec", "plan", "tasks"}
    assert package.payload.baseline == base.baseline
    assert package.payload.candidate == base.candidate
    assert package.payload.change_ref == base.change_ref
    assert package.payload.review_refs == base.review_refs
    assert package.payload.method_ref == base.method_ref
    assert package.payload.method_resource_refs == base.method_resource_refs

    # every role is archived: no document may be missing from the returned bytes
    assert set(document_bytes) == set(contents)
    # each returned document is exactly the captured Markdown, UTF-8 exact
    assert document_bytes["spec"] == contents["spec"].encode("utf-8")
    assert document_bytes["plan"] == contents["plan"].encode("utf-8")
    assert document_bytes["tasks"] == contents["tasks"].encode("utf-8")
    # the archived bytes must match the digest the accepted record pins per role
    recorded = {document.role: document.source_ref.capture.content_digest.hex
                for document in package.payload.documents}
    for role in ("spec", "plan", "tasks"):
        assert hashlib.sha256(document_bytes[role]).hexdigest() == recorded[role]
        source = next(doc.source_ref for doc in package.payload.documents
                      if doc.role == role)
        assert source.byte_length == len(document_bytes[role])

    # A former payload with model-authored subject/source pins is not a valid
    # alternate version of the contract, even when it carries real ref objects.
    legacy = dict(envelope, payload=package_payload_projection(base))
    with pytest.raises(ApplicationError, match="WORK_ACTION_GENERATION_OUTPUT_INVALID"):
        DeclaredGenerationPort._decode_output(
            canonical_bytes(legacy).decode(), context,
            change_ref=base.change_ref, review_ref=base.review_refs[0],
            method_ref=base.method_ref, method_resource_refs=base.method_resource_refs,
            baseline=base.baseline, candidate=base.candidate)

    incomplete = dict(envelope, document_contents={"spec": contents["spec"],
                                                    "plan": contents["plan"]})
    with pytest.raises(ApplicationError, match="WORK_ACTION_GENERATION_OUTPUT_INVALID"):
        DeclaredGenerationPort._decode_output(
            canonical_bytes(incomplete).decode(), context,
            change_ref=base.change_ref, review_ref=base.review_refs[0],
            method_ref=base.method_ref, method_resource_refs=base.method_resource_refs,
            baseline=base.baseline, candidate=base.candidate)
