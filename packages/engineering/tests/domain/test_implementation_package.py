"""Closed implementation-package domain contracts; identities are synthetic values only.

ProposalRefs and ApprovalRefs below are deliberately pure synthetic identities.
They do not stand for resolved proposals, BindingProof, approval, or trusted actors.
"""
from hashlib import sha256

import pytest
from ordessa_infrastructure.encoding import canonical_bytes

from ordessa_engineering.domain.approvals.refs import ApprovalRef
from ordessa_engineering.domain.approvals.scope import EnvironmentRef
from ordessa_engineering.domain.artifacts.method_binding import ExactMethodResourceRef, MethodRef
from ordessa_engineering.domain.artifacts.models import MethodContent
from ordessa_engineering.domain.artifacts.refs import ArtifactRevisionRef
from ordessa_engineering.domain.changes.models import ChangeSet
from ordessa_engineering.domain.changes.refs import ProposalRef
from ordessa_engineering.domain.changes.repository_baseline import seal_repository_baseline
from ordessa_engineering.domain.common.mechanisms.codec import canonical_value
from ordessa_engineering.domain.common.models.identity import ActorRef, Scope
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from ordessa_engineering.domain.packages.codec import decode_package, encode_package
from ordessa_engineering.domain.packages.models import (
    ImplementationPackage, ImplementationPackagePayload, PackageCoverage,
    PackageDerivation, PackageFile, package_manifest_digest,
)
from ordessa_engineering.domain.packages.refs import ImplementationPackageRef


SCOPE = Scope('synthetic-realm', 'synthetic-project')
ACTOR = ActorRef('synthetic-actor', 'human', 'fixture-issuer')
CREATED_AT = '2026-10-11T12:00:00.000000Z'


def digest(seed):
    return Digest('sha256', sha256(seed.encode()).hexdigest())


def blob(seed, media_type='application/json'):
    raw = seed.encode()
    return BlobRef(digest(seed), len(raw), media_type, 'fixture-object-' + seed.replace(' ', '-'))


def proposal(number):
    # Synthetic ref only; no Proposal record or resolver is constructed here.
    return ProposalRef(SCOPE.realm_id, SCOPE.project_id, f'change-{number}',
                       f'proposal-{number}', digest(f'proposal-{number}'))


def revision(number):
    return ArtifactRevisionRef(SCOPE.realm_id, SCOPE.project_id, f'artifact-{number}',
                               f'revision-{number}', digest(f'revision-{number}'))


def baseline():
    return seal_repository_baseline(SCOPE, 'repo-1', 'none', None, ()).ref


def package_file(operation='add', *, path='src/new.py', rename_from=None,
                 before=None, proposal_refs=None):
    return PackageFile('repo-1', path, operation, before, rename_from,
                       tuple(proposal_refs or (proposal(1),)), 'synthetic file purpose')


def make_package(*, operations=(), allowed_actions=('generate_package',),
                 proposals=None, coverage=None, method_content=None,
                 output_digest=None):
    proposal_refs = tuple(proposals or (proposal(1),))
    manifest = tuple(operations)
    acceptance = ()
    coverage_rows = tuple(coverage) if coverage is not None else tuple(
        PackageCoverage(ref, (blob(f'instruction-{i}'),),
                       tuple(f.path for f in manifest if ref in f.proposal_refs),
                       acceptance, (revision(20 + i),))
        for i, ref in enumerate(proposal_refs, 1))
    manifest_digest = package_manifest_digest(manifest) if output_digest is None else output_digest
    method = MethodRef('method-test', '1.0.0', 1, digest('method snapshot'))
    payload = ImplementationPackagePayload(
        implementation_intent_id='intent-test', change_set=ChangeSet(proposal_refs),
        design_targets=(revision(1),),
        # Synthetic pure reference; it is not an issued or verified Grant.
        authorization_refs=(ApprovalRef(SCOPE.realm_id, SCOPE.project_id,
                                        'synthetic-approval', digest('grant digest')) ,),
        method_ref=method, required_review_refs=(), baseline_snapshots=(baseline(),),
        resolved_file_manifest=manifest, instructions_ref=blob('top-level-instructions'),
        skill_snapshot_refs=(),
        execution_profile_ref=EnvironmentRef('env-test', 'profile-test', digest('profile')),
        allowed_actions=tuple(allowed_actions), acceptance_requirements=acceptance,
        proposal_coverage=coverage_rows, method_content=method_content,
        derivation=PackageDerivation(digest('intent'), (blob('generator-input'),),
                                     'generator-test', '0.1', manifest_digest),
    )
    return ImplementationPackage(SCOPE, 'package-test', CREATED_AT, ACTOR, payload)


def test_full_typed_package_fixture_closed_codec_roundtrip():
    row = package_file()
    package = make_package(operations=(row,), allowed_actions=('generate_package', 'edit_repository'))
    encoded = encode_package(package)
    restored = decode_package(encoded)
    assert restored == package
    assert restored.ref == ImplementationPackageRef(SCOPE.realm_id, SCOPE.project_id,
                                                      'package-test', package.digest)
    assert restored.payload.resolved_file_manifest == (row,)
    assert restored.payload.proposal_coverage[0].files == ('src/new.py',)


def test_duplicate_and_missing_proposal_coverage_are_rejected():
    first, second = proposal(1), proposal(2)
    coverage_first = PackageCoverage(first, (blob('one'),), (), (), (revision(31),))
    with pytest.raises(ReferenceError, match='PACKAGE_COVERAGE_INCOMPLETE'):
        make_package(proposals=(first, second), coverage=(coverage_first, coverage_first))
    with pytest.raises(ReferenceError, match='PACKAGE_COVERAGE_INCOMPLETE'):
        make_package(proposals=(first, second), coverage=(coverage_first,))


def test_wrong_manifest_digest_is_rejected():
    with pytest.raises(ReferenceError, match='PACKAGE_MANIFEST_DIGEST_MISMATCH'):
        make_package(operations=(package_file(),), output_digest=digest('wrong manifest'))


def test_add_modify_and_rename_require_operation_specific_before_facts():
    with pytest.raises(ReferenceError, match='INVALID_PACKAGE_FILE'):
        PackageFile('repo-1', 'new.py', 'add', digest('unexpected before'), None,
                    (proposal(1),), 'add')
    with pytest.raises(ReferenceError, match='INVALID_PACKAGE_FILE'):
        PackageFile('repo-1', 'existing.py', 'modify', None, None,
                    (proposal(1),), 'modify')
    with pytest.raises(ReferenceError, match='INVALID_SCHEMA'):
        PackageFile('repo-1', 'new.py', 'rename', digest('before'), None,
                    (proposal(1),), 'rename without source')


def test_empty_edit_manifest_rejected_but_readonly_package_can_be_empty():
    with pytest.raises(ReferenceError, match='PACKAGE_EDIT_MANIFEST_REQUIRED'):
        make_package(allowed_actions=('generate_package', 'edit_repository'))
    readonly = make_package(allowed_actions=('run_checks',))
    assert readonly.payload.resolved_file_manifest == ()
    assert decode_package(encode_package(readonly)) == readonly


def test_foreign_scope_proposal_coverage_is_rejected():
    foreign = ProposalRef('other-realm', 'other-project', 'foreign-change',
                          'foreign-proposal', digest('foreign-proposal'))
    row = PackageCoverage(foreign, (blob('foreign-instruction'),), (), (), (revision(41),))
    with pytest.raises(ReferenceError, match='PACKAGE_COVERAGE_INCOMPLETE'):
        make_package(coverage=(row,))


def test_unknown_action_is_rejected():
    with pytest.raises(ReferenceError, match='INVALID_PACKAGE_ACTIONS'):
        make_package(allowed_actions=('generate_package', 'run_arbitrary_code'))


def _method_content(value):
    method = MethodRef('method-test', '1.0.0', 1, digest('method snapshot'))
    resource = ExactMethodResourceRef(method, 'method.yaml', digest('resource'), 'method-schema')
    return MethodContent.from_value(resource, value)


def test_method_content_value_is_in_package_digest_and_codec_rejects_tampering():
    package = make_package(method_content=_method_content({'steps': ['preserve exact source']}))
    value = canonical_value(encode_package(package))
    value['payload']['method_content']['value']['steps'][0] = 'tampered source'
    with pytest.raises(ReferenceError):
        decode_package(canonical_bytes(value))


def test_method_content_changes_package_digest():
    original = _method_content({'body': 'original'})
    altered = _method_content({'body': 'altered'})
    assert make_package(method_content=original).digest != make_package(method_content=altered).digest
