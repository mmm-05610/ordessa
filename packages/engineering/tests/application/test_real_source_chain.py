"""Published 2.7 source chain through original owners; local authority is controlled.

Files are authored explicitly by the caller and read by the real finite file
adapter. The provider below is synthetic; live JEV uses the same builder in
the bounded evidence probe, never this test's answer as a real model result.
"""
import asyncio
from contextlib import contextmanager
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
from ordessa_decision import DecisionAnswer, FilesystemEvidenceStore, default_host_limits
from ordessa_decision.evidence import EvidenceScope
from ordessa_decision.definitions.values import MAX_JOB_DOCUMENT_BYTES
from ordessa_engineering.adapters.decision.source_job import SourceReviewJobServices
from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ordessa_engineering.adapters.filesystem.project_sources import ProjectSourceMaterials
from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl
from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.adapters.decision.source_bindings import DeclaredSourceReviewBindings
from ordessa_engineering.adapters.decision.source_reviewer import DecisionReviewerSource
from ordessa_engineering.application.api.method_publication import publish_method_declaration
from ordessa_engineering.application.assembly import (
    EngineeringPorts, build_engineering_service, build_method_management,
)
from ordessa_engineering.application.contracts.commands import CommandContext
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.usecases.reviews.admission import EngineeringReviewAdmission, review_observations
from ordessa_engineering.domain.artifacts.provenance import SourceLocator, SourceRef, VersionCapture
from ordessa_engineering.domain.changes.codec import encode_proposal
from ordessa_engineering.domain.changes.models import Proposal, SourceChange
from ordessa_engineering.domain.changes.ref_codec import decode_proposal_ref
from ordessa_engineering.domain.common.mechanisms.hashing import record_digest
from ordessa_engineering.domain.common.models.identity import ActorRef, Scope
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.packages.codec import encode_package, decode_package_ref
from ordessa_engineering.domain.packages.models import ImplementationPackage, PreparedPackagePayload, PackageDocument
from ordessa_engineering.domain.reviews.codec import encode_plan
from ordessa_engineering.domain.reviews.ref_codec import decode_review_ref
from ordessa_engineering.methods import load_method
from ordessa_engineering.methods.definitions.models import MethodSource


ROOT = Path(__file__).resolve().parents[4]
CANDIDATE = ROOT / 'methods/incremental-engineering/candidates/2.7.0'
SCOPE = Scope('local-source-chain-test', 'caller-authored-project')
AUTHOR = ActorRef('local-source-author', 'human', 'controlled-local-caller')
REVIEWER = ActorRef('local-decision-reviewer', 'service', 'explicit-host-selection')
NOW = '2026-10-14T12:00:00.000000Z'
PRINCIPAL = 'controlled-local-principal'
BASE_RAW = b'# Example DID\nThe caller edits a local document. Ordessa records its exact version and review.\n'
CANDIDATE_RAW = BASE_RAW + b'Package preparation records caller supplied spec, plan and tasks references.\n'


def context(request_id):
    return CommandContext(SCOPE, PRINCIPAL, AUTHOR, request_id, NOW, 'source-chain-test')


class ControlledLocalAccess:
    """Only this fixture's scoped caller; does not mint product permissions."""
    def require(self, ctx, operation):
        if ctx.scope != SCOPE or ctx.principal_id != PRINCIPAL:
            raise ApplicationError('ACCESS_DENIED')


class ControlledMethodManagement:
    """Explicit local test admission, not a production authorization producer."""
    @contextmanager
    def guard_management(self, ctx, operation, method, parameters):
        ControlledLocalAccess().require(ctx, operation)
        if operation != 'engineering.methods.control':
            raise ApplicationError('METHOD_MANAGEMENT_UNAVAILABLE')
        yield record_digest('controlled-local-method-control', {
            'scope':asdict(ctx.scope), 'operation':operation, 'parameters':parameters})


class ControlledDecisionProvider:
    binding_ref = 'controlled-source-review-provider/1'
    settings_digest = 'sha256:' + 'c' * 64

    def __init__(self, answer='passed', *, expected_sources=(BASE_RAW, CANDIDATE_RAW)):
        self.answer, self.questions = answer, []
        self.expected_sources = expected_sources

    async def decide(self, question, ctx):
        self.questions.append(question)
        assert question.bounded_state['sources'][0]['text'] == self.expected_sources[0].decode()
        assert question.bounded_state['sources'][1]['text'] == self.expected_sources[1].decode()
        ctx.claim(question, self.settings_digest)
        return DecisionAnswer(question.question_id, 'choice', self.answer,
            {'provider_binding':self.binding_ref, 'controlled':True, 'selection_status':'unique',
             'question_digest':question.question_digest, 'provider_settings_digest':self.settings_digest,
             'resolved_model':'controlled', 'requested_model':'controlled',
             'protocol_validation_version':'controlled/1',
             'probabilities':{key:float(key == self.answer) for key in question.options}}, {'status':'unknown'})


def source(logical_document, version, raw):
    return SourceRef(logical_document, 'document',
        SourceLocator('document', provider='project-files', document_id=logical_document),
        VersionCapture(version, Digest('sha256', sha256(raw).hexdigest())),
        NOW, AUTHOR, 'text/markdown', len(raw))


def build_local_chain(directory, provider, *, method_directory=CANDIDATE, material_entries=None,
                      caller_material_index=None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    library = EngineeringLibrary.create((directory/'engineering.sqlite').resolve(),
        library_id='local-source-chain', schema_version=16)
    factory, snapshots = SQLiteUoWFactory(library), SQLiteSnapshotStore(library)
    loaded = load_method(MethodSource(method_directory, 'method.json'), FileResourceReader())
    assert loaded.ok, loaded.error
    published = publish_method_declaration(loaded.value, snapshots)
    assert published.ok, published.error
    method = published.value
    controls = SQLiteMethodControl(factory, snapshots)
    management = build_method_management(factory, access=ControlledLocalAccess(),
        snapshots=snapshots, management=ControlledMethodManagement())
    # Public control command persists original events/journal. Publication itself
    # supplies neither control nor a compiled/adopted workflow.
    management.control(method, context('enable-local-declaration'), expected_version=0,
        enabled=True, reason='controlled local source-chain validation')
    project = directory/'caller-files'
    project.mkdir()
    mappings = []
    entries = material_entries if material_entries is not None else (
        ('example-DID', 'v1', 'did-v1.md', BASE_RAW),
        ('example-DID', 'v2', 'did-v2.md', CANDIDATE_RAW),
        ('example-spec', 'v1', 'spec.md', b'Caller supplied specification.\n'),
        ('example-plan', 'v1', 'plan.md', b'Caller supplied implementation plan.\n'),
        ('example-tasks', 'v1', 'tasks.md', b'Caller supplied tasks.\n'),
    )
    for logical, version, path, raw in entries:
        (project/path).write_bytes(raw)
        mappings.append((source(logical, version, raw), path))
    baseline, candidate = (mappings[i][0] for i in (0,1))
    materials = ProjectSourceMaterials(factory, scope=SCOPE, root=project,
                                       source_mappings=tuple(mappings))
    bindings = DeclaredSourceReviewBindings(factory, controls, scope=SCOPE, method_ref=method,
        baseline=baseline, candidate=candidate, action_id='incremental.review-change',
        binding_resource_id='source-review-binding', criteria_resource_id='change-review-criteria',
        prompt_resource_id='change-review-prompt', result_schema_resource_id='review-result-schema',
        reviewer_roles=('reviewer',),
        **({'caller_materials_ref':mappings[caller_material_index][0],
            'caller_input_schema_resource_id':'caller-review-input-schema'}
           if caller_material_index is not None else {}))
    plan = bindings.plan(context('select-plan'), 'local-source-review')
    blobs = SQLiteBlobStore(library)
    (directory/'decision-runs').mkdir(mode=0o700)
    evidence_owner = FilesystemEvidenceStore(directory/'decision-runs')
    evidence_scope = EvidenceScope('principal', 'local-source-chain')
    services = SourceReviewJobServices(provider, evidence_owner, lambda ctx: ctx,
        lambda *_: evidence_scope, lambda ctx, request_id: replace(ctx, request_id=request_id),
        host_limits={**default_host_limits(), 'timeout_seconds':240.0},
        job_document_max_bytes=MAX_JOB_DOCUMENT_BYTES)
    reviewer = DecisionReviewerSource(factory, blobs, controls, materials, bindings,
        scope=SCOPE, principal_id=PRINCIPAL, reviewer=REVIEWER, roles=('reviewer',), services=services)
    admission = EngineeringReviewAdmission(factory, controls, None, reviewer,
        source_materials=materials, method_guard=controls, source_review_bindings=bindings)
    service = build_engineering_service(factory, EngineeringPorts(ControlledLocalAccess(),
        review_admission=admission, source_materials=materials, method_guard=controls,
        source_review_bindings=bindings, blobs=blobs))
    with controls.guard(context('exact-package-resources'), method) as definition:
        resources = tuple(controls.resource_ref(context('exact-package-resources'), method,
            item.resource_id) for item in definition.resources)
    return SimpleNamespace(library=library, factory=factory, snapshots=snapshots, method=method,
        management=management, controls=controls, materials=materials, bindings=bindings,
        plan=plan, blobs=blobs, evidence_owner=evidence_owner, evidence_scope=evidence_scope,
        services=services, reviewer=reviewer,
        admission=admission, service=service, project=project, mappings=mappings,
        baseline=baseline, candidate=candidate, resources=resources)


def read_job_answers(env, receipt):
    """Original current job result/summary, never a fabricated old terminal."""
    _, questions, job, request = env.reviewer._inputs(context('read-original-job'), env.plan,
        receipt['request_version'], receipt['fence'])
    return env.services.reader(context('read-original-job'), request.request_id).read(
        request.request_id, job, questions,
        provider_binding=env.services.decision_provider.binding_ref,
        provider_settings=env.services.decision_provider.settings_digest)


def close_chain(env):
    env.reviewer.close()
    env.materials.close()
    env.library.close()


@pytest.fixture
def local_chain(tmp_path):
    env = build_local_chain(tmp_path, ControlledDecisionProvider())
    try:
        yield env
    finally:
        close_chain(env)


def test_requirement_standard_and_exact_method_resources_are_one_binding(local_chain):
    env = local_chain
    selected = env.bindings.review_inputs(context('selected-standard'), env.plan)
    standard = selected['standard']
    assert env.plan.requirement.criterion_set_ref.criterion_set_id == standard.standard_id
    assert env.plan.requirement.criterion_set_ref.digest.hex == standard.resource_ref.sha256
    with env.admission.guard_plan(context('request-admission'), env.plan):
        with env.factory.begin(SCOPE) as uow:
            uow.commit()


def draft(env):
    proposal = Proposal(SCOPE, 'caller-draft', NOW, AUTHOR, 'unspecified-change',
        'Record the explicitly edited local DID', 'Same document v1 and v2; no document custody',
        (), (), (), (), env.method, (), None, (), 2,
        SourceChange(env.baseline, env.candidate, env.resources))
    value = decode_json(encode_proposal(proposal))
    return {key:value[key] for key in ('intent','rationale','mutations','basis_sources',
        'claim_refs','evidence_links','method_ref','review_requirement_templates',
        'implementation_intent','supersedes_refs','source_change')}


def create_proposal(env, request_id='create-source-change'):
    result = asyncio.run(env.service.execute('engineering.proposals.create',
        {'change_id':None, 'expected_version':0, 'draft':draft(env)}, context(request_id)))
    return decode_proposal_ref(result.result['proposal_ref'])


def request_and_run_review(env, *, run_cleanup=None):
    requested = asyncio.run(env.service.execute('engineering.reviews.request',
        {'plan':decode_json(encode_plan(env.plan))}, context('request-source-review')))
    with env.factory.begin(SCOPE, 'read') as uow:
        request = uow.reviews.get_request(env.plan.review_id)
    async def run_once():
        try:
            return await env.reviewer.run_review(context('run-source-review'), env.plan, request)
        finally:
            if run_cleanup is not None:
                await run_cleanup()
    raw_ref = asyncio.run(run_once())
    receipt = decode_json(env.blobs.read_verified(raw_ref))
    try:
        recorded = asyncio.run(env.service.execute('engineering.reviews.record', {
            'review_id':env.plan.review_id, 'request_version':request.version,
            'fence':request.fence, 'raw_response_utf8':env.blobs.read_verified(raw_ref).decode()},
            context('record-source-review')))
    except ApplicationError as exc:
        # Native completion survives a later Engineering admission refusal.
        # Retain the original run identity for the bounded probe's cold reader.
        exc.decision_run_id = receipt['run_id']
        exc.decision_status = 'completed'
        raise
    return requested, recorded, receipt


def associate_and_freeze(env, proposal_ref, review_ref):
    associated = asyncio.run(env.service.execute('engineering.proposals.associate_review', {
        'proposal_ref':asdict(proposal_ref), 'expected_version':1, 'review_ref':asdict(review_ref)},
        context('associate-source-review')))
    successor = decode_proposal_ref(associated.result['proposal_ref'])
    documents = tuple(PackageDocument(role, env.mappings[i][0])
                      for role,i in (('spec',2),('plan',3),('tasks',4)))
    package = ImplementationPackage(SCOPE, 'caller-prepared-package', NOW, AUTHOR,
        PreparedPackagePayload(env.baseline, env.candidate, successor, (review_ref,),
                               env.method, env.resources, documents))
    wire = decode_json(encode_package(package))
    frozen = asyncio.run(env.service.execute('engineering.packages.freeze',
        {'record':wire}, context('freeze-source-package')))
    assert frozen.result['dispatchable'] is False
    return successor, package, wire, frozen


def run_full_chain(env):
    proposal_ref = create_proposal(env)
    _, recorded, receipt = request_and_run_review(env)
    assert recorded.result['verdict'] == 'pass'
    review_ref = decode_review_ref(recorded.result['review_ref'])
    successor, package, wire, frozen = associate_and_freeze(env, proposal_ref, review_ref)
    return SimpleNamespace(proposal_ref=proposal_ref, review_ref=review_ref, successor=successor,
        package=package, wire=wire, frozen=frozen,
        package_ref=decode_package_ref(frozen.result['package_ref']), receipt=receipt)


def test_public_service_exact_source_review_package_and_sqlite_reconnect(local_chain, monkeypatch):
    from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteEngineeringUoW
    env = local_chain
    commits = []
    original = SQLiteEngineeringUoW.commit
    def observed(uow):
        active = getattr(env.library._method_declaration_fences, 'values', ())
        commits.append(bool(active))
        return original(uow)
    monkeypatch.setattr(SQLiteEngineeringUoW, 'commit', observed)
    result = run_full_chain(env)
    assert any(commits)
    assert len(env.services.decision_provider.questions) == 1
    assert asyncio.run(env.service.execute('engineering.packages.freeze',
        {'record':result.wire}, context('freeze-source-package'))) == result.frozen
    native = read_job_answers(env, result.receipt)
    assert native.operation_ref == result.receipt['run_id'] and len(native.answers) == 1
    assert result.receipt['request_version'] == 0 and result.receipt['fence'] == 1
    path = env.library.path
    env.library.close()
    reopened = EngineeringLibrary.open(path, library_id='local-source-chain')
    try:
        service = build_engineering_service(SQLiteUoWFactory(reopened), EngineeringPorts(ControlledLocalAccess()))
        package = asyncio.run(service.query('engineering.references.resolve',
            {'ref':asdict(result.package_ref)}, context('reconnect-package')))
        proposal = asyncio.run(service.query('engineering.proposals.get',
            {'proposal_ref':asdict(result.successor)}, context('reconnect-proposal')))
        assert package == result.package
        assert proposal.source_change.review_refs == (result.review_ref,)
        assert asyncio.run(service.execute('engineering.packages.freeze',
            {'record':result.wire}, context('freeze-source-package'))) == result.frozen
    finally:
        reopened.close()


@pytest.mark.parametrize('failure', ('changed_content','unavailable','untrusted','disabled_method'))
def test_original_chain_refuses_changed_unavailable_or_untrusted_inputs(local_chain, failure):
    env = local_chain
    proposal_ref = create_proposal(env)
    _, recorded, _ = request_and_run_review(env)
    review_ref = decode_review_ref(recorded.result['review_ref'])
    if failure == 'changed_content':
        (env.project/'did-v2.md').write_bytes(CANDIDATE_RAW.replace(b'caller', b'Caller'))
        expected = 'SOURCE_CONTENT_MISMATCH'
    elif failure == 'unavailable':
        (env.project/'did-v2.md').unlink()
        expected = 'SOURCE_UNAVAILABLE'
    elif failure == 'untrusted':
        env.reviewer.close()
        expected = 'UNTRUSTED_REVIEWER'
    else:
        env.management.control(env.method, context('disable-declaration'), expected_version=1,
            enabled=False, reason='controlled explicit stop')
        expected = 'METHOD_DISABLED'
    with pytest.raises(ApplicationError, match=expected):
        associate_and_freeze(env, proposal_ref, review_ref)
    with env.factory.begin(SCOPE, 'read') as uow:
        assert uow.proposals.get_proposal(proposal_ref).source_change.review_refs == ()
    assert env.library._connection.execute('SELECT count(*) FROM eng_packages').fetchone()[0] == 0


@pytest.mark.parametrize('answer', ('not_passed','unknown'))
def test_actual_decision_nonpass_cannot_prepare_package(tmp_path, answer):
    env = build_local_chain(tmp_path, ControlledDecisionProvider(answer))
    try:
        proposal_ref = create_proposal(env)
        _, recorded, _ = request_and_run_review(env)
        assert recorded.result['verdict'] != 'pass'
        review_ref = decode_review_ref(recorded.result['review_ref'])
        with pytest.raises(ApplicationError):
            associate_and_freeze(env, proposal_ref, review_ref)
        assert env.library._connection.execute('SELECT count(*) FROM eng_packages').fetchone()[0] == 0
    finally:
        close_chain(env)


def test_one_shot_provider_cleanup_runs_before_call_event_loop_closes(local_chain):
    env = local_chain
    provider = env.services.decision_provider
    original_decide = provider.decide
    loops = []
    async def decide(question, ctx):
        loops.append(asyncio.get_running_loop())
        return await original_decide(question, ctx)
    async def cleanup():
        assert asyncio.get_running_loop() is loops[0]
        assert not loops[0].is_closed()
        loops.append('closed-on-original-loop')
    provider.decide = decide
    _, recorded, _ = request_and_run_review(env, run_cleanup=cleanup)
    assert recorded.result['verdict'] == 'pass'
    assert loops[1] == 'closed-on-original-loop'


