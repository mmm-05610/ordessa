"""Reusable original-authority fixture for pending JEV evidence integration.

The source snippets and token are controlled test inputs only. They do not
represent authenticated user testimony, a human grant, or model qualification.
The proposal writer is isolated fixture setup; request, method admission,
preparation and Artifact capture use the original Engineering/InstanceAccess
owners and the same SQLite library.
"""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl
from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.application.contracts.snapshots import EngineeringTargetBindings
from ordessa_engineering.application.orchestration.method_bridge import MethodBridge
from ordessa_engineering.application.usecases.changes.proposals import ProposalUseCases
from ordessa_engineering.application.usecases.material_closure import verify_material
from ordessa_engineering.application.usecases.reviews.admission import EngineeringReviewAdmission
from ordessa_engineering.application.usecases.reviews.service import ReviewUseCases
from ordessa_engineering.application.usecases.support.methods import MethodUseCases
from ordessa_engineering.domain.artifacts.method_binding import MethodRef, ExactMethodResourceRef
from ordessa_engineering.domain.artifacts.models import (
    Artifact, ArtifactRevision, MethodContent, MethodPayload,
)
from ordessa_engineering.domain.artifacts.provenance import (
    Claim, ClaimRef, EvidenceLink, ExcerptCapture, SourceLocator, SourceRef,
)
from ordessa_engineering.domain.changes.models import ProposalEvidenceLink
from ordessa_engineering.domain.common.models.selection import ContentSelector
from ordessa_engineering.domain.common.models.values import Digest, UtcInstant
from ordessa_engineering.domain.reviews.requirements import (
    ReviewRequirementTemplate, SubjectSelector, TemplateCheck, TemplateTarget,
)
from ordessa_engineering.domain.reviews.targets import Target, TargetSet
from ordessa_engineering.methods.definitions.models.compiled import thaw_value
from ordessa_interfaces.system_access.access_control.authentication import AccessGrant, InstanceAccessAuthority
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_system_access_bindings.engineering import EngineeringCommandAccess
from ordessa_server.composition.engineering_business_bindings import (
    ConfiguredReviewPhase, OriginalProposalBindings,
)
from ordessa_server.composition.engineering_method_management import OriginalMethodManagement
from ordessa_server.composition.engineering_jev_work import OriginalJevWork
from ordessa_server.composition.engineering_reviewer_source import JEV_SOURCE_CAPABILITY
from test_method_per_claim import ROOT, published
from test_proposal_usecases import ACTOR, CREATED_AT, SCOPE as ENGINEERING_SCOPE, SyntheticAccess, _ctx, _proposal_ref


SERVER_SCOPE = Scope(ENGINEERING_SCOPE.realm_id, ENGINEERING_SCOPE.project_id)
OPERATIONS = (
    'engineering.methods.adopt', 'engineering.artifacts.create',
    'engineering.reviews.request', 'engineering.reviews.record',
    'engineering.reviews.query', JEV_SOURCE_CAPABILITY,
)
METHOD_ROOT = ROOT / 'candidates/2.3.0'
PHASE_KEY = 'source_review'
MATERIAL_SLOTS = ('proposal_ref', 'source_captures', 'claim_bindings')


def _did_document(statement, *, title):
    return {
        'document_type': 'did', 'schema_version': 1, 'title': title,
        'intent': 'Exercise exact published DID schema binding for pending JEV evidence.',
        'claims': [{'claim_id': 'claim-one', 'kind': 'observation',
            'statement': statement, 'source_ids': ['source-support'],
            'counter_source_ids': ['source-counter']}],
        'goals': ['Keep evidence and review bindings exact.'],
        'non_goals': ['Qualify a model or authenticate a human grant.'],
        'change_plan': [{'path': 'fixture.txt', 'change': 'Use a controlled fixture.',
            'reason_claim_ids': ['claim-one']}],
        'risks': [], 'rollback': 'Discard the isolated SQLite fixture.',
        'acceptance': [{'acceptance_id': 'fixture-acceptance',
            'description': 'The fixture uses the released DID schema.',
            'test_ids': ['test-engineering-jev-work']}],
        'open_questions': [],
    }


def _method_payload(snapshot, method_ref, value):
    """Build MethodPayload against the exact frozen DID schema resource."""
    specs = [item for item in snapshot.program.document_definitions
        if item.document_type == 'did']
    if len(specs) != 1:
        raise AssertionError('fixture requires one published DID schema')
    spec = specs[0]
    stored = [r for r in snapshot.resources if r.resource_id == spec.schema_resource.resource_id
        and r.digest == spec.schema_resource.sha256]
    if len(stored) != 1:
        raise AssertionError('published DID schema resource did not resolve exactly')
    resource = stored[0]
    exact = ExactMethodResourceRef(method_ref, resource.logical_path,
        Digest('sha256', resource.digest), resource.resource_id)
    schema = thaw_value(spec.value_schema)
    schema_id = schema.get('$id')
    if type(schema_id) is not str:
        raise AssertionError('published DID schema has no exact schema id')
    return MethodPayload('application/json', schema_id, MethodContent.from_value(exact, value))


def _source(blobs, source_id, raw):
    digest = Digest('sha256', hashlib.sha256(raw).hexdigest())
    blob = blobs.put_verified(raw, digest, 'text/plain')
    return SourceRef(source_id, 'chat_message',
        SourceLocator('chat_message', provider='controlled-fixture',
            conversation_id='jev-pending-work-fixture', message_id=source_id),
        ExcerptCapture(blob, digest, ContentSelector('whole_capture'), 'fixture-capture-v1'),
        UtcInstant(CREATED_AT), ACTOR, 'text/plain', len(raw))


def build_original_pending_work(root: Path):
    """Create a fresh original-library fixture; caller must close ``library``."""
    root.mkdir(parents=True, exist_ok=False)
    library = EngineeringLibrary.create((root / 'original.sqlite').resolve(),
        library_id='controlled-original-jev-pending-work', schema_version=10)
    factory = SQLiteUoWFactory(library)
    authority = InstanceAccessAuthority(lambda: 'temporary-controlled-token',
        principal_id='controlled-jev-service', legacy_principal=None,
        grants=(AccessGrant(SERVER_SCOPE, OPERATIONS),))
    access = EngineeringCommandAccess(authority)
    caller = authority.authenticate('Bearer temporary-controlled-token')

    def admitted(operation, identity):
        return access.admit(caller, SERVER_SCOPE, operation,
            request_id=identity, trace_id=identity)

    snapshot = published(library, METHOD_ROOT)
    released = snapshot.ref
    method_ref = MethodRef(released.method_id, released.release_version,
        released.schema_version, Digest('sha256', released.snapshot_digest))
    snapshots = SQLiteSnapshotStore(library)
    controls = SQLiteMethodControl(factory, snapshots)
    methods = MethodUseCases(factory, access, snapshots, OriginalMethodManagement(access, SERVER_SCOPE))
    with admitted('engineering.methods.adopt', 'fixture-method-adopt') as context:
        methods.adopt(method_ref, context, expected_version=0)

    blobs = SQLiteBlobStore(library)
    support = _source(blobs, 'source-support', b'Controlled source supports the fixture claim.')
    counter = _source(blobs, 'source-counter', b'Controlled source contradicts the fixture claim.')
    body = _did_document('A controlled statement with captured evidence.', title='Pending JEV fixture')
    statement = body['claims'][0]['statement']
    claim = Claim('claim-one', ContentSelector('json_pointer', pointer='/claims/0/statement'),
        Digest('sha256', hashlib.sha256(
            __import__('ordessa_infrastructure.encoding', fromlist=['canonical_bytes'])
            .canonical_bytes(statement)).hexdigest()))
    links = tuple(EvidenceLink(claim.claim_id, source, ContentSelector('whole_capture'), relation,
        'Controlled captured relation for fixture only.')
        for source, relation in ((support, 'supports'), (counter, 'contradicts')))
    base = ArtifactRevision(ENGINEERING_SCOPE, 'jev-pending-did', 'jev-pending-base', CREATED_AT, ACTOR,
        _method_payload(snapshot, method_ref,
            _did_document('Prior controlled statement.', title='Prior DID fixture')),
        schema_version=2, method_refs=(method_ref,))
    proposed = ArtifactRevision(ENGINEERING_SCOPE, 'jev-pending-did', 'jev-pending-proposed',
        CREATED_AT, ACTOR, _method_payload(snapshot, method_ref, body),
        parent_revision_refs=(base.ref,), schema_version=2, sources=(support, counter),
        claims=(claim,), evidence_links=links, method_refs=(method_ref,))
    with factory.begin(ENGINEERING_SCOPE) as uow:
        uow.engineering.create(Artifact(ENGINEERING_SCOPE, proposed.artifact_id, 'plan', CREATED_AT))
        verify_material(base, uow.engineering.validated_budget())
        base_ref = uow.engineering.append_revision(base, expected_version=0)
        verify_material(proposed, uow.engineering.validated_budget())
        proposed_ref = uow.engineering.append_revision(proposed, expected_version=1)
        if proposed_ref != proposed.ref:
            raise AssertionError('fixture revision identity changed during persistence')
        uow.commit()

    target = Target('proposed', proposed.ref)
    target_binding = EngineeringTargetBindings(ENGINEERING_SCOPE, TargetSet((target,)),
        ((target, 'did'),), MATERIAL_SLOTS, ('reviewer',), PHASE_KEY,
        workflow_node_id=PHASE_KEY)
    bridge = MethodBridge()
    requirements = bridge.review_requirements(snapshot, target_binding, revisions=(proposed,))
    template_target = TemplateTarget('proposed', SubjectSelector('proposed_mutation', 0))
    templates = tuple(ReviewRequirementTemplate(ENGINEERING_SCOPE,
        'jev-pending-template-' + requirement.criterion_set_ref.criterion_set_id, 1,
        requirement.purpose, (template_target,), method_ref, requirement.criterion_set_ref,
        tuple(TemplateCheck(template_target, key.criterion_id, key.claim_id)
            for key in requirement.required_check_keys), requirement.eligible_reviewer_roles,
        PHASE_KEY) for requirement in requirements)
    claim_ref = ClaimRef(proposed.ref, claim.claim_id, claim.statement_digest)
    proposal_links = tuple(ProposalEvidenceLink(claim_ref, source,
        ContentSelector('whole_capture'), relation, 'Controlled fixture relation is preserved.')
        for source, relation in ((support, 'supports'), (counter, 'contradicts')))
    draft = {
        'intent': 'Review one controlled claim against captured source fixtures.',
        'rationale': 'Test-only proposal; it carries no authenticated human assertion.',
        'mutations': [{'artifact_id': proposed.artifact_id, 'operation': 'revise',
            'base_ref': asdict(base_ref), 'proposed_ref': asdict(proposed.ref)}],
        'basis_sources': [asdict(support), asdict(counter)],
        'claim_refs': [asdict(claim_ref)],
        'evidence_links': [asdict(link) for link in proposal_links],
        'method_ref': asdict(method_ref),
        'review_requirement_templates': [asdict(item) for item in templates],
        'implementation_intent': None, 'supersedes_refs': [],
    }
    created = ProposalUseCases(factory, SyntheticAccess()).create(
        {'change_id': None, 'expected_version': 0, 'draft': draft}, _ctx())
    proposal_ref = _proposal_ref(created.result['proposal_ref'])
    phases = (ConfiguredReviewPhase(PHASE_KEY, ('reviewer',), material_inputs=(
        ('source_captures', proposed.ref), ('claim_bindings', proposed.ref)),
        workflow_node_id=PHASE_KEY),)
    bindings = OriginalProposalBindings(factory, controls, scope=ENGINEERING_SCOPE,
        proposal_ref=proposal_ref, phases=phases)
    review_admission = EngineeringReviewAdmission(factory, controls, bindings)
    reviews = ReviewUseCases(factory, access, review_admission, blobs=blobs)

    with admitted('engineering.reviews.request', 'fixture-review-request') as context:
        phase_bindings = bindings.resolve_intent_bindings(context, method_ref, proposal_ref)
        with factory.begin(context.scope, 'read') as uow:
            budget = uow.proposals.validated_budget()
            proposal = uow.proposals.get_proposal(proposal_ref, budget=budget)
            revisions = uow.proposals.resolve_revision_graph(
                tuple(m.proposed_ref for m in proposal.mutations)
                + tuple(m.base_ref for m in proposal.mutations if m.base_ref is not None)
                + tuple(c.owner_revision_ref for c in proposal.claim_refs), budget)
            owners = tuple(uow.engineering.get_artifact(m.artifact_id) for m in proposal.mutations)
        plan_requirements = bridge.proposal_review_requirements(snapshot, phase_bindings,
            proposal=proposal, artifacts=owners, revisions=revisions)
        requirement = next(item for item in plan_requirements
            if item.criterion_set_ref.criterion_set_id == 'source-review')
        plan = bridge.review_plan(snapshot, phase_bindings[0], requirement,
            'jev-pending-original-review', proposal=proposal, artifacts=owners,
            revisions=revisions, phase_bindings=phase_bindings)
        reviews.request({'plan': asdict(plan)}, context)
        with factory.begin(context.scope, 'read') as uow:
            request = uow.reviews.get_request(plan.review_id)

    work = OriginalJevWork(factory=factory, access=access, scope=SERVER_SCOPE,
        methods=controls, bindings=bindings, admission=review_admission, blobs=blobs)
    return {
        'library': library, 'factory': factory, 'authority': authority, 'access': access,
        'caller': caller, 'admitted': admitted, 'snapshot': snapshot,
        'method_ref': method_ref, 'proposal_ref': proposal_ref, 'plan': plan,
        'request': request, 'bindings': bindings, 'admission': review_admission,
        'reviews': reviews, 'work': work, 'blobs': blobs, 'server_scope': SERVER_SCOPE,
    }
