"""Original owners end to end; SDK fake HTTP is zero network/model qualification.

The published controlled method is an existing Engineering test asset. No
SyntheticAccess, synthetic reviewer evidence, trust port or management guard is
used. These tests prove protocol/authority behavior, never real JEV semantics.
"""
import asyncio
from dataclasses import asdict, replace
import json

import httpx2
import pytest

from test_method_review_bridge import publish
from decision_runtime.definitions import DecisionQuestion, PolicyRef, ReadContext, digest
from decision_runtime.evidence import FileEvidenceSink
from ordessa_decision_jev import JevDecisionProvider, JevProviderSettings
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.snapshots import EngineeringTargetBindings
from ordessa_engineering.application.orchestration.method_bridge import MethodBridge
from ordessa_engineering.application.usecases.artifacts import ArtifactUseCases
from ordessa_engineering.application.usecases.support.methods import MethodUseCases
from ordessa_engineering.application.usecases.reviews.admission import EngineeringReviewAdmission
from ordessa_engineering.application.usecases.reviews.service import ReviewUseCases
from ordessa_engineering.domain.artifacts.method_binding import MethodRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.reviews.targets import Target, TargetSet
from ordessa_engineering.domain.reviews.target_codec import decode_subject_ref
from ordessa_interfaces.system_access.access_control.authentication import AccessGrant, InstanceAccessAuthority
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_system_access_bindings.engineering import EngineeringCommandAccess
from ordessa_server.composition.engineering_method_management import OriginalMethodManagement
from ordessa_server.composition.engineering_jev_run import (
    ConfiguredJevQuestion, execute_jev_review, review_binding,
)
from ordessa_server.composition.engineering_reviewer_source import (
    JEV_SOURCE_CAPABILITY, OriginalJevReviewerSource, encode_review_run,
)

SCOPE = Scope('controlled-source-realm', 'controlled-source-project')
OPERATIONS = ('engineering.methods.adopt', 'engineering.artifacts.create',
    'engineering.reviews.request', 'engineering.reviews.record', 'engineering.reviews.query',
    JEV_SOURCE_CAPABILITY)


@pytest.fixture
def original_work(tmp_path):
    library = EngineeringLibrary.create((tmp_path/'original.sqlite').resolve(),
        library_id='controlled-real-source-protocol', schema_version=10)
    authority = InstanceAccessAuthority(lambda:'controlled-fixture-token',
        principal_id='controlled-review-service', legacy_principal=None,
        grants=(AccessGrant(SCOPE, OPERATIONS),))
    access = EngineeringCommandAccess(authority)
    caller = authority.authenticate('Bearer controlled-fixture-token')
    factory = SQLiteUoWFactory(library)
    snapshot, _ = publish(library, tmp_path/'method-source')
    released = snapshot.ref
    method = MethodRef(released.method_id, released.release_version,
        released.schema_version, Digest('sha256', released.snapshot_digest))
    controls = SQLiteMethodControl(factory, SQLiteSnapshotStore(library))
    methods = MethodUseCases(factory, access, SQLiteSnapshotStore(library),
        OriginalMethodManagement(access, SCOPE))

    def admitted(operation, identity):
        return access.admit(caller, SCOPE, operation, request_id=identity, trace_id=identity)

    with admitted('engineering.methods.adopt', 'adopt') as context:
        methods.adopt(method, context, expected_version=0)
    with admitted('engineering.artifacts.create', 'material') as context:
        created = ArtifactUseCases(factory, access).create({'kind':'other',
            'initial':{'media_type':'application/json', 'schema_id':'urn:controlled:source',
                'inline_value':{'statement':'Controlled source protocol specimen.'}}}, context)
        target = Target('primary', decode_subject_ref(created.result['revision_ref']))
        binding = EngineeringTargetBindings(context.scope, TargetSet((target,)),
            ((target,'test-document'),), ('proposal_ref',), ('reviewer',), 'source-phase')
    # Explicit controlled business configuration, not a reviewer trust port.
    class ConfiguredBusiness:
        def resolve_bindings(self, context, selected, phase):
            assert context.scope == binding.scope and selected == method and phase == binding.phase_key
            return binding
    requirement = MethodBridge().review_requirements(snapshot, binding)[0]
    plan = MethodBridge().review_plan(snapshot, binding, requirement, 'controlled-review')
    admission = EngineeringReviewAdmission(factory, controls, ConfiguredBusiness())
    reviews = ReviewUseCases(factory, access, admission, blobs=SQLiteBlobStore(library))
    with admitted('engineering.reviews.request', 'request') as context:
        reviews.request({'plan':asdict(plan)}, context)
        with factory.begin(context.scope, 'read') as uow:
            request = uow.reviews.get_request(plan.review_id)
    try:
        yield library, factory, access, authority, caller, admitted, plan, request, reviews, admission
    finally:
        library.close()


def original_run(work, tmp_path):
    _, factory, access, _, _, _, plan, request, _, _ = work
    policy = PolicyRef('controlled.source-protocol', '1', digest('policy', asdict(plan.requirement)))
    binding = review_binding(plan, request)
    questions = tuple(ConfiguredJevQuestion(key, DecisionQuestion('check-'+str(i), '1', 'choice',
        {'engineering_review':dict(binding, check_key=asdict(key)),
            'specimen':'Controlled fake-HTTP source protocol, not real model qualification.'},
        'Controlled protocol check only.', options={name:name for name in
            ('satisfied','violated','insufficient','unknown')}, policy_ref=policy), ())
        for i,key in enumerate(plan.check_keys))
    calls = []
    def handle(http_request):
        payload = json.loads(http_request.content)
        calls.append(payload)
        identity = next(iter(payload['questions']))
        return httpx2.Response(200, json={'model':'jev-1.13.0','usage':{},'answers':{
            identity:{'type':'choice','choice':'satisfied','confidence':1,
                'probabilities':{'satisfied':1,'violated':0,'insufficient':0,'unknown':0}}}})
    provider = JevDecisionProvider(JevProviderSettings(binding_ref='controlled-real-jev-adapter'),
        secret_resolver=lambda _:'fake-http-only', transport=httpx2.MockTransport(handle))
    context = ReadContext(object(), 'controlled-original-evidence-reader')
    evidence_root = tmp_path/'durable'
    evidence_root.mkdir(mode=0o700)
    sink = FileEvidenceSink(evidence_root, read_context=context)
    run, flow, result = asyncio.run(execute_jev_review(plan=plan, request=request,
        questions=questions, provider=provider, evidence_sink=sink, read_context=context,
        request_id='controlled-decision-run', task_revision='1', review_ref='controlled-original-source-code',
        qualification_fixture=True))
    source = OriginalJevReviewerSource(access=access, scope=SCOPE,
        blobs=SQLiteBlobStore(factory.library), evidence_reader=sink, read_context=context,
        provider=provider, runs=(run,), roles=('reviewer',), accepted_models=('jev-1.13.0',), flows=(flow,),
        qualification_fixture=True)
    return source, run, calls, provider, sink


def test_original_record_response_commits_complete_source_and_manual_gate(original_work, tmp_path):
    _, factory, _, _, _, admitted, plan, request, reviews, admission = original_work
    source, run, calls, provider, sink = original_run(original_work, tmp_path)
    admission.source = source
    try:
        with admitted('engineering.reviews.record', 'record') as context:
            recorded = reviews.record_response(plan.review_id, encode_review_run(run), context,
                expected_request_version=request.version, fence=request.fence)
            assert recorded.status == 'completed'
        with admitted('engineering.reviews.query', 'gate') as context:
            snapshot = reviews.query_set(plan.requirement, context)
            record = snapshot.reviews[0].record
            assert record.complete and record.raw_response_ref is not None
            assert record.reviewer_evidence.reviewer.actor_id == provider.binding_ref
            assert all(o.result == 'indeterminate' for o in record.observations)
            assert not reviews.gate(plan.requirement, context).satisfied
        assert len(calls) == len(plan.check_keys)
    finally:
        asyncio.run(provider.close()); asyncio.run(sink.close())


@pytest.mark.parametrize('mutation,code', [
    ('raw','REVIEW_RAW_RESPONSE_INVALID'),
    ('request-version','REVIEW_REQUEST_CHANGED'),
    ('copied-context','ACCESS_AUTHORITY_UNAVAILABLE'),
    ('source-grant','ACCESS_DENIED'),
])
def test_original_source_rejects_mismatch_without_committed_review(original_work, tmp_path, mutation, code):
    _, factory, _, authority, _, admitted, plan, request, reviews, admission = original_work
    source, run, _, provider, sink = original_run(original_work, tmp_path)
    admission.source = source
    raw, version = encode_review_run(run), request.version
    try:
        if mutation == 'source-grant':
            authority.replace_grants((AccessGrant(SCOPE, tuple(o for o in OPERATIONS if o != JEV_SOURCE_CAPABILITY)),))
            # The original authority must issue a new caller after epoch change.
            caller = authority.authenticate('Bearer controlled-fixture-token')
            manager = source.access.admit(caller, SCOPE, 'engineering.reviews.record', request_id='negative', trace_id='negative')
        else:
            manager = admitted('engineering.reviews.record', 'negative')
        with manager as context:
            if mutation == 'raw': raw = b'{"unbound":"wrong original raw response"}'
            if mutation == 'request-version': version += 1
            if mutation == 'copied-context': context = replace(context)
            with pytest.raises(ApplicationError, match=code):
                reviews.record_response(plan.review_id, raw, context,
                    expected_request_version=version, fence=request.fence)
            with factory.begin(plan.scope, 'read') as uow:
                assert uow.reviews.get_request(plan.review_id).state == 'requested'
        # Only the real record-response owner may advance this request.
    finally:
        asyncio.run(provider.close()); asyncio.run(sink.close())
