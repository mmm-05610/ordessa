"""Real SQLite/W10 material lineage plus assigned role, with explicit Unit peers.

The native query and phase selector are test peers, not production reviewers.
All command admission, immutable method/revision/journal and schema15 role
records use their original owners. No principal is asserted to be a human.
"""
from dataclasses import asdict, replace
import hashlib
import json
from types import SimpleNamespace

import pytest

from test_reviewer_assignments_schema15 import (
    _publish_with_identity_constraint, _TestManagement, _SyntheticUnitRecords,
    _unit, _assign, _revoke, WIRE_SCOPE, TOKEN, ASSIGN, REVOKE,
    AccessGrant, InstanceAccessAuthority, EngineeringCommandAccess,
    EngineeringLibrary, SQLiteUoWFactory, SQLiteMethodControl, MethodUseCases,
    SyntheticAccess, DOMAIN_SCOPE, _ctx, MethodBridge, EngineeringTargetBindings,
    Target, TargetSet, EngineeringService, ApplicationError, Digest, BlobRef,
    canonical_bytes, build_reviewer_assignment_usecases, SQLiteUnitReviewerAuthority,
)
from ordessa_engineering.adapters.review_sources import (
    SQLiteReviewAuthorshipSource, ConfiguredMaterialSubmission, SQLiteUnitReviewBindings,
)
from ordessa_engineering.application.api import NativeReviewInvocation
from ordessa_engineering.application.contracts.commands import CommandKey
from ordessa_engineering.application.contracts.review_authorship import SOURCE_BOUND_POLICY
from ordessa_engineering.application.usecases.artifacts import ArtifactUseCases
from ordessa_engineering.domain.artifacts.refs import ArtifactRevisionRef


CREATE = 'engineering.artifacts.create'


@pytest.fixture
def env(tmp_path):
    lib = EngineeringLibrary.create((tmp_path/'material-review.sqlite').resolve(),
        library_id='material-role80', schema_version=15)
    try:
        snapshot, method, store = _publish_with_identity_constraint(lib, tmp_path/'method',
            identity_constraint=SOURCE_BOUND_POLICY)
        factory = SQLiteUoWFactory(lib)
        control = SQLiteMethodControl(factory, store)
        MethodUseCases(factory, SyntheticAccess(), store, _TestManagement()).adopt(
            method, _ctx(), expected_version=0)
        authority = InstanceAccessAuthority(lambda: TOKEN, principal_id='material-role-issuer',
            legacy_principal=None, grants=(AccessGrant(WIRE_SCOPE, (CREATE, ASSIGN, REVOKE)),))
        access = EngineeringCommandAccess(authority)
        caller = authority.authenticate('Bearer '+TOKEN)
        with access.admit(caller, WIRE_SCOPE, CREATE, request_id='formal-material', trace_id='test') as ctx:
            result = ArtifactUseCases(factory, access).create({
                'kind':'plan', 'initial':{'media_type':'application/json',
                    'schema_id':'urn:test:material-role80', 'inline_value':{'declaration':'fixed material'}},
                'method_refs':[asdict(method)]}, ctx)
        raw = result.result['revision_ref']
        revision = ArtifactRevisionRef(raw['realm_id'], raw['project_id'], raw['artifact_id'],
            raw['revision_id'], Digest(**raw['digest']))
        target = Target('primary', revision)
        selected = EngineeringTargetBindings(DOMAIN_SCOPE, TargetSet((target,)),
            ((target, 'test-document'),), ('proposal_ref',), ('reviewer',), 'review',
            workflow_node_id='review')
        bridge = MethodBridge()
        plan = bridge.review_plan(snapshot, selected, bridge.review_requirements(snapshot, selected)[0],
            'material-role-review80')
        with factory.begin(DOMAIN_SCOPE) as uow:
            request = uow.reviews.create_plan(plan)
            uow.commit()

        class _MaterialPhasePeer:
            """Explicit fixture selection; it does not authenticate a submitter."""
            def __init__(self): self.factory, self.methods = factory, control
            def resolve_bindings(self, *args): return selected
            def material_inputs(self, *args): return ()
            def resolve_review_submission(self, *args): return None
        phase = _MaterialPhasePeer()
        origin = SQLiteReviewAuthorshipSource(factory, control, review_bindings=phase,
            material_submissions=(ConfiguredMaterialSubmission(revision,
                CommandKey(DOMAIN_SCOPE.realm_id, caller.principal_id, 'formal-material')),))
        records = _SyntheticUnitRecords()
        records.acp_prompt_input_digest = lambda unit, params: 'sha256:'+hashlib.sha256(
            canonical_bytes({'unit':unit,'params':params})).hexdigest()
        def query(_ctx, unit_ref, _plan, _request, *, purpose):
            return {'test_query':unit_ref['unitId'], 'purpose':purpose}, 'fixture-input:'+unit_ref['unitId']
        assignments = build_reviewer_assignment_usecases(factory, method_control=control,
            records=records, expected_access=access, expected_scope=WIRE_SCOPE,
            unit_query_factory=query, authorship_source=origin)
        service = EngineeringService(factory, access, reviewer_assignments=assignments)
        reviewer = _unit('independently-assigned-reviewer')
        calls = []
        def invocation(ctx, p, r, *, prompt_binding):
            calls.append(prompt_binding)
            return NativeReviewInvocation(reviewer, 'original-review-operation',
                {'sessionId':'test-session','prompt':[{'type':'text','text':prompt_binding}]}, object())
        reader = SQLiteUnitReviewBindings(factory, control, records, review_bindings=phase,
            invocation_resolver=invocation, authorship_source=origin)
        reviewer_authority = SQLiteUnitReviewerAuthority(factory, expected_access=access,
            expected_scope=WIRE_SCOPE, assignments=assignments, method_control=control,
            unit_records=records, unit_query_factory=query, authorship_source=origin)
        raw_ref = BlobRef(Digest('sha256','c'*64), 4, 'application/octet-stream', 'test-observation')
        observation = Digest('sha256','d'*64)
        yield locals()
    finally:
        lib.close()


def _binding(e, ctx):
    return e['reader'].resolve_unit_review(ctx, e['plan'], e['request'],
        standard=e['snapshot'].program.standard_definitions[0])


def test_formal_material_can_be_independently_reviewed_without_inventing_an_author_unit(env):
    e = env
    _assign(e, e['reviewer'], 'assign-material-reviewer')
    with e['access'].admit(e['caller'], WIRE_SCOPE, ASSIGN, request_id='material-evidence', trace_id='test') as ctx:
        binding = _binding(e, ctx)
        constraints = binding.reviewer_identity_constraints
        assert constraints['authorUnitRef'] is None
        assert constraints['authorship']['source_kind'] == 'authenticated_material_submitter'
        assert constraints['authorship']['material_proofs'][0]['submitter_principal_id'] == ctx.principal_id
        assert ctx.authenticated_actor.actor_kind == 'service'
        with e['reviewer_authority'].guard_unit_reviewer(ctx, e['plan'], e['request'], binding,
                e['raw_ref'], e['observation']) as evidence:
            assert evidence.roles == ('reviewer',)
            assert evidence.reviewer.actor_kind == 'agent'
    with e['factory'].begin(DOMAIN_SCOPE, 'read') as uow:
        assignment, _ = uow.reviewer_assignments.active_for_review(e['plan'].review_id)
    assert assignment.author_unit_ref_bytes is None
    assert assignment.reviewer_unit_ref == e['reviewer']
    assert not hasattr(evidence, 'accepted')


def test_material_origin_does_not_supply_missing_or_revoked_reviewer_role(env):
    e = env
    with e['access'].admit(e['caller'], WIRE_SCOPE, ASSIGN, request_id='no-role', trace_id='test') as ctx:
        binding = _binding(e, ctx)
        with pytest.raises(ApplicationError, match='REVIEWER_ASSIGNMENT_UNAVAILABLE'):
            with e['reviewer_authority'].guard_unit_reviewer(ctx, e['plan'], e['request'], binding,
                    e['raw_ref'], e['observation']):
                pytest.fail('source lineage cannot create a reviewer role')
    _assign(e, e['reviewer'], 'role-to-revoke')
    with e['factory'].begin(DOMAIN_SCOPE, 'read') as uow:
        assignment, _ = uow.reviewer_assignments.active_for_review(e['plan'].review_id)
    _revoke(e, assignment.ref, 'revoke-material-role', 'end assigned role')
    with e['access'].admit(e['caller'], WIRE_SCOPE, ASSIGN, request_id='revoked-role', trace_id='test') as ctx:
        with pytest.raises(ApplicationError, match='REVIEWER_ASSIGNMENT_UNAVAILABLE'):
            with e['reviewer_authority'].guard_unit_reviewer(ctx, e['plan'], e['request'], _binding(e,ctx),
                    e['raw_ref'], e['observation']):
                pytest.fail('revoked role must refuse')


def test_material_authorship_claim_and_arbitrary_author_unit_cannot_replace_original_source(env):
    e = env
    with pytest.raises(ApplicationError, match='INVALID_INPUT'):
        _assign(e, e['reviewer'], 'invented-author', _unit('invented-author'))
    _assign(e, e['reviewer'], 'original-source-assignment')
    with e['access'].admit(e['caller'], WIRE_SCOPE, ASSIGN, request_id='changed-proof', trace_id='test') as ctx:
        binding = _binding(e, ctx)
        constraints = dict(binding.reviewer_identity_constraints)
        constraints['authorship'] = {**constraints['authorship'], 'source_kind':'human'}
        altered = replace(binding, reviewer_identity_constraints=constraints)
        with pytest.raises(ApplicationError, match='REVIEW_AUTHOR_SOURCE_INVALID'):
            with e['reviewer_authority'].guard_unit_reviewer(ctx, e['plan'], e['request'], altered,
                    e['raw_ref'], e['observation']):
                pytest.fail('captured authorship DTO cannot authenticate itself')
