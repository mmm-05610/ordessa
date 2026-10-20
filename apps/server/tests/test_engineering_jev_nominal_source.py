"""Recorded JEV choice-source candidate against a real frozen method snapshot.

All calls use SDK MockTransport and controlled fixture authorities. These cases
do not qualify a real model or reviewer. Answer completeness is a structural
fact from the original JEV parser and matching durable evidence; it does not
attest semantic support or model quality.
"""
import asyncio
from dataclasses import asdict
import hashlib
import json

import httpx2
import pytest

from decision_runtime.definitions import DecisionQuestion, PolicyRef, ReadContext, digest
from decision_runtime.evidence import FileEvidenceSink
from ordessa_decision_jev import JevDecisionProvider, JevProviderSettings
from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl
from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.snapshots import EngineeringTargetBindings
from ordessa_engineering.application.orchestration.method_bridge import MethodBridge
from ordessa_engineering.application.usecases.artifacts import ArtifactUseCases
from ordessa_engineering.application.usecases.reviews.admission import EngineeringReviewAdmission
from ordessa_engineering.application.usecases.reviews.service import ReviewUseCases
from ordessa_engineering.application.usecases.support.methods import MethodUseCases
from ordessa_engineering.domain.artifacts.method_binding import MethodRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.reviews.targets import Target, TargetSet
from ordessa_engineering.domain.reviews.target_codec import decode_subject_ref
from ordessa_engineering.methods import compile_method
from ordessa_engineering.methods.definitions.models import (
    CapabilityDescriptor, CompilationCapabilities, MethodSource,
)
from ordessa_engineering.methods.definitions.models.identity import method_digest
from ordessa_engineering.methods.loading.loader import load_method
from ordessa_engineering.application.usecases.publish_snapshot import freeze_method
from ordessa_interfaces.system_access.access_control.authentication import AccessGrant, InstanceAccessAuthority
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_server.composition.engineering_jev_run import (
    ConfiguredJevQuestion, execute_jev_review, review_binding,
)
from ordessa_server.composition.engineering_method_management import OriginalMethodManagement
from ordessa_server.composition.engineering_reviewer_source import (
    JEV_SOURCE_CAPABILITY, OriginalJevReviewerSource, encode_review_run, frozen_input_digest,
)
from ordessa_system_access_bindings.engineering import EngineeringCommandAccess


SCOPE = Scope('controlled-recorded-realm', 'controlled-recorded-project')
OPTIONS = {
    'supported': 'The frozen evidence supports the complete statement.',
    'contradicted': 'The frozen evidence contradicts the complete statement.',
    'insufficient': 'The frozen evidence is insufficient to decide.',
}
OPTION_STATUS = {
    'supported': 'satisfied',
    'contradicted': 'violated',
    'insufficient': 'insufficient',
}
OPERATIONS = (
    'engineering.methods.adopt', 'engineering.artifacts.create',
    'engineering.reviews.request', 'engineering.reviews.record',
    'engineering.reviews.query', JEV_SOURCE_CAPABILITY,
)


def _write_published_choice_method(library, root, *, mixed=False):
    """Load, compile and publish this test's own versioned nominal source."""
    root.mkdir()
    workflow = {
        'schema_version': 1, 'entry': 'done',
        'steps': [{'id': 'done', 'kind': 'stop', 'outcome': 'finished'}],
        'stop_outcomes': ['finished'], 'wait_kinds': [],
    }
    schema = {'type': 'object', 'additionalProperties': True}
    conversion = {
        'contract_version': 'ordessa.nominal-choice-status/1',
        'answer_kind': 'choice', 'option_statuses': OPTION_STATUS,
        'tie': 'unknown', 'missing_answer': 'unknown',
        'incomplete_answer': 'unknown', 'truncated_input': 'unknown',
        'unmapped_option': 'unknown',
    }
    quality = {
        'contract_version': 'ordessa.review-quality-admission/1',
        'activation': 'matching_validated_evaluation_required',
        'missing_evaluation': 'manual', 'unresolved_model': 'manual',
    }
    criteria = []
    for criterion_id, statement in (
        ('criterion-alpha', 'First independently frozen choice criterion.'),
        ('criterion-beta', 'Second independently frozen choice criterion.'),
    ):
        criteria.append({
            'criterion_id': criterion_id, 'statement': statement,
            'applies_to': ['test-document'], 'required_inputs': ['proposal_ref'],
            'checks': [{
                'capability_id': 'ordessa.decision.evaluate',
                'interface_version': '1.0.0',
                'bindings': {
                    'nominal_answer_conversion': conversion,
                    'quality_admission': quality,
                },
            }],
            'policy': {
                'satisfied': 'manual', 'violated': 'block',
                'insufficient': 'block', 'unknown': 'manual',
            },
            'answer_vocabulary': {
                'kind': 'choice',
                'options': [
                    {'option_id': key, 'description': value}
                    for key, value in OPTIONS.items()
                ],
            },
        })
    if mixed:
        for identifier, capability in (('source-integrity', 'ordessa.sources.integrity'),
                ('claim-coverage', 'ordessa.claims.coverage')):
            criteria.append({'criterion_id':identifier, 'statement':'Controlled mechanical fixture.',
                'applies_to':['test-document'], 'required_inputs':['proposal_ref'],
                'checks':[{'capability_id':capability,'interface_version':'1.0.0','bindings':{}}],
                'policy':{'satisfied':'pass','violated':'block','insufficient':'manual','unknown':'manual'}})
    standard = {
        'schema_version': 1, 'standard_id': 'controlled-recorded-standard',
        'revision': '1.4.0', 'purpose': 'quality', 'criteria': criteria,
        'reduction': {
            'required_criteria': 'all_applicable',
            'empty_applicable_set': 'error', 'priority': ['block', 'manual', 'pass'],
        },
    }
    resources = []
    for identifier, kind, path, value, media_type in (
        ('workflow.main', 'workflow', 'workflow.yaml', workflow, 'application/yaml'),
        ('document.test.schema', 'document_schema', 'schema.json', schema, 'application/schema+json'),
        ('standard.recorded', 'standard', 'standard.yaml', standard, 'application/yaml'),
    ):
        raw = json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
        (root / path).write_bytes(raw)
        resources.append({
            'id': identifier, 'kind': kind, 'path': path,
            'media_type': media_type, 'sha256': hashlib.sha256(raw).hexdigest(),
        })
    descriptor = CapabilityDescriptor(
        'ordessa.decision.evaluate', 'check', '1.0.0',
        method_digest('capability-contract', {}), {},
    )
    descriptors = (descriptor,) + (tuple(CapabilityDescriptor(identifier, 'check', '1.0.0',
        method_digest('capability-contract', {}), {},) for identifier in
        ('ordessa.sources.integrity','ordessa.claims.coverage')) if mixed else ())
    capabilities = CompilationCapabilities(descriptors, trust_class='host')
    manifest = {
        'schema_version': 1, 'method_id': 'test.recorded-jev-nominal',
        'release_version': '1.0.0', 'compiler_contract': 'ordessa.methods/v1',
        'entry': {'resource': 'workflow.main'},
        'resources': resources,
        'documents': [{'document_type': 'test-document', 'schema': {'resource': 'document.test.schema'}}],
        'requires': [{'capability_id':item.capability_id, 'kind':item.kind,
            'interface_version':item.interface_version, 'contract_digest':item.contract_digest}
            for item in descriptors],
    }
    (root / 'method.yaml').write_text(json.dumps(manifest), encoding='utf-8')
    loaded = load_method(MethodSource(root), FileResourceReader())
    assert loaded.ok, loaded.error
    compiled = compile_method(loaded.value, capabilities, 'test.recorded-compiler/1')
    assert compiled.ok, compiled.error

    class Catalog:
        def read_current(self):
            return capabilities

    store = SQLiteSnapshotStore(library)
    frozen = freeze_method(compiled.value, store, store, capability_catalog=Catalog())
    assert frozen.ok, frozen.error
    snapshot = store.get(frozen.value.ref)
    standard_row = next(s for s in snapshot.program.standard_definitions
        if s.standard_id == 'controlled-recorded-standard')
    assert standard_row.revision == '1.4.0'
    assert len(standard_row.criteria) == (4 if mixed else 2)
    return snapshot, store


def _prepare(tmp_path, selected_option, *, mutation=None, call_log=None, mixed=False):
    library = EngineeringLibrary.create((tmp_path / 'original.sqlite').resolve(),
        library_id='controlled-recorded-source', schema_version=10)
    factory = SQLiteUoWFactory(library)
    authority = InstanceAccessAuthority(lambda: 'controlled-fixture-token',
        principal_id='controlled-review-service', legacy_principal=None,
        grants=(AccessGrant(SCOPE, OPERATIONS),))
    access = EngineeringCommandAccess(authority)
    caller = authority.authenticate('Bearer controlled-fixture-token')
    admitted = lambda operation, identity: access.admit(
        caller, SCOPE, operation, request_id=identity, trace_id=identity)
    snapshot, store = _write_published_choice_method(library, tmp_path / 'method-source', mixed=mixed)
    released = snapshot.ref
    method = MethodRef(released.method_id, released.release_version,
        released.schema_version, Digest('sha256', released.snapshot_digest))
    method_store = SQLiteSnapshotStore(library)
    controls = SQLiteMethodControl(factory, method_store)
    methods = MethodUseCases(factory, access, method_store,
        OriginalMethodManagement(access, SCOPE))
    with admitted('engineering.methods.adopt', 'adopt') as context:
        methods.adopt(method, context, expected_version=0)

    with admitted('engineering.artifacts.create', 'material') as context:
        created = ArtifactUseCases(factory, access).create({
            'kind': 'other',
            'initial': {
                'media_type': 'application/json', 'schema_id': 'urn:controlled:recorded',
                'inline_value': {'statement': 'Controlled frozen source fixture.'},
            },
        }, context)
        target = Target('primary', decode_subject_ref(created.result['revision_ref']))
        bindings = EngineeringTargetBindings(context.scope, TargetSet((target,)),
            ((target, 'test-document'),), ('proposal_ref',), ('reviewer',), 'recorded-phase')

    class ConfiguredBusiness:
        def resolve_bindings(self, context, selected, phase):
            assert context.scope == bindings.scope and selected == method and phase == bindings.phase_key
            return bindings

    requirement = MethodBridge().review_requirements(snapshot, bindings)[0]
    plan = MethodBridge().review_plan(snapshot, bindings, requirement, 'controlled-recorded-review')
    request = None
    admission = EngineeringReviewAdmission(factory, controls, ConfiguredBusiness())
    reviews = ReviewUseCases(factory, access, admission, blobs=SQLiteBlobStore(library))
    with admitted('engineering.reviews.request', 'request') as context:
        reviews.request({'plan': asdict(plan)}, context)
        with factory.begin(context.scope, 'read') as uow:
            request = uow.reviews.get_request(plan.review_id)

    standard = next(s for s in snapshot.program.standard_definitions
        if s.standard_id == plan.requirement.criterion_set_ref.criterion_set_id)
    check_options = {
        option.option_id: option.description
        for option in next(c for c in standard.criteria
            if c.answer_vocabulary is not None).answer_vocabulary.options
    }
    policy = PolicyRef('controlled.recorded-source', '1', digest('policy', asdict(plan.requirement)))
    binding = review_binding(plan, request)
    configured = []
    for index, key in enumerate(plan.check_keys):
        if next(c for c in standard.criteria if c.criterion_id == key.criterion_id).answer_vocabulary is None:
            continue
        state = {
            'engineering_review': dict(binding, check_key=asdict(key)),
            'controlled_fixture': 'not production humanGrant; fixed source-protocol specimen',
        }
        options = dict(check_options)
        if mutation == 'wrong-description' and index == 0:
            first = next(iter(options))
            options[first] += ' altered'
        question = DecisionQuestion(
            'recorded-check-' + str(index), '1', 'choice', state,
            'Select the choice that best describes the frozen controlled fixture.',
            options=options, policy_ref=policy,
        )
        input_digest = frozen_input_digest(question.bounded_state)
        input_truncated = False
        if mutation == 'missing-input-fact' and index == 0:
            input_digest = None
        elif mutation == 'wrong-input-digest' and index == 0:
            input_digest = 'sha256:' + '0' * 64
        configured.append(ConfiguredJevQuestion(key, question, (), input_digest, input_truncated))

    calls = call_log if call_log is not None else []
    def handle(http_request):
        payload = json.loads(http_request.content)
        calls.append(payload)
        identity = next(iter(payload['questions']))
        probabilities = {key: (1 if key == selected_option else 0) for key in OPTIONS}
        return httpx2.Response(200, json={
            'model': 'jev-1.13.0', 'usage': {}, 'answers': {
                identity: {
                    'type': 'choice', 'choice': selected_option, 'confidence': 1,
                    'probabilities': probabilities,
                },
            },
        })

    provider = JevDecisionProvider(JevProviderSettings(binding_ref='controlled-recorded-jev'),
        secret_resolver=lambda _: 'mock-transport-only', transport=httpx2.MockTransport(handle))
    read_context = ReadContext(object(), 'controlled-recorded-evidence-reader')
    evidence_root = tmp_path / 'durable-evidence'
    evidence_root.mkdir(mode=0o700)
    sink = FileEvidenceSink(evidence_root, read_context=read_context)
    try:
        run, flow, result = asyncio.run(execute_jev_review(
            plan=plan, request=request, questions=tuple(configured), provider=provider,
            evidence_sink=sink, read_context=read_context,
            request_id='controlled-recorded-decision-run', task_revision='1',
            review_ref='controlled-recorded-source-code', standard=standard,
            nominal_evidence_only=mixed,
        ))
        source = OriginalJevReviewerSource(access=access, scope=SCOPE,
            blobs=SQLiteBlobStore(library), evidence_reader=sink, read_context=read_context,
            provider=provider, runs=(run,), roles=('reviewer',),
            accepted_models=('jev-1.13.0',), flows=(flow,))
        admission.source = source
        return {
            'library': library, 'factory': factory, 'admitted': admitted,
            'plan': plan, 'request': request, 'reviews': reviews, 'run': run,
            'calls': calls, 'provider': provider, 'sink': sink,
            'result': result,
        }
    except BaseException:
        asyncio.run(provider.close())
        asyncio.run(sink.close())
        library.close()
        raise


def _close(work):
    asyncio.run(work['provider'].close())
    asyncio.run(work['sink'].close())
    work['library'].close()


@pytest.mark.parametrize('selected_option', tuple(OPTIONS))
def test_recorded_three_choice_source_stays_manual_after_original_recording(tmp_path, selected_option):
    work = _prepare(tmp_path, selected_option)
    try:
        plan, request = work['plan'], work['request']
        with work['admitted']('engineering.reviews.record', 'record') as context:
            recorded = work['reviews'].record_response(plan.review_id,
                encode_review_run(work['run']), context,
                expected_request_version=request.version, fence=request.fence)
            assert recorded.status == 'completed'
        with work['admitted']('engineering.reviews.query', 'gate') as context:
            result = work['reviews'].query_set(plan.requirement, context)
            record = result.reviews[0].record
            assert record.complete and record.raw_response_ref is not None
            assert all(observation.result == 'indeterminate' for observation in record.observations)
            assert not work['reviews'].gate(plan.requirement, context).satisfied
        assert len(work['calls']) == len(plan.check_keys) == 2
        assert all(check.answer.value == selected_option for check in work['run'].checks)
    finally:
        _close(work)


@pytest.mark.parametrize('mutation,code', [
    ('wrong-description', 'REVIEW_SOURCE_INVALID'),
    ('missing-input-fact', 'REVIEW_SOURCE_INCOMPLETE'),
    ('wrong-input-digest', 'REVIEW_SOURCE_INCOMPLETE'),
])
def test_recorded_nominal_source_rejects_bad_frozen_input_before_http(tmp_path, mutation, code):
    calls = []
    with pytest.raises(ApplicationError, match=code):
        _prepare(tmp_path, 'supported', mutation=mutation, call_log=calls)
    assert calls == []
