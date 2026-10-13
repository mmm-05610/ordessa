"""Explicit schema14 acceptance storage on the original Engineering authority.

These are persistence/DDL fixtures only. They do not establish a real grant,
human authorization, Submission qualification, or adoption use-case success.
"""
import sqlite3
import hashlib

import pytest

from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.migrations import migrate_schema13
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.common.models.identity import Scope
from ordessa_engineering.domain.common.models.identity import ActorRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.artifacts.models import Artifact, ArtifactRevision, InlinePayload
from ordessa_engineering.domain.artifacts.method_binding import MethodRef
from ordessa_engineering.domain.artifacts.refs import ArtifactRevisionRef
from ordessa_engineering.domain.approvals.consent import (
    AuthorizationIntent, ApprovalGrant, ConsentPolicyRef, ConversationEvidence,
    ConversationNotice, ConversationSource, ConsentChallenge,
)
from ordessa_engineering.domain.changes.application_plan import HeadExpectation
from ordessa_engineering.domain.changes.adoption import (
    AcceptancePlan, AcceptanceTarget, AcceptanceReceipt, encode_acceptance_receipt,
    decode_acceptance_receipt,
)
from ordessa_engineering.domain.reviews.models import CheckKey, CriterionSetRef, ReviewRequirement
from ordessa_engineering.domain.reviews.refs import ReviewRef, SubmissionRef
from ordessa_engineering.domain.reviews.targets import Target, TargetSet
from ordessa_engineering.application.usecases.material_closure import verify_material


SCOPE = Scope('acceptance-test-realm', 'acceptance-test-project')
NOW = '2026-10-11T12:00:00.000000Z'
LATER = '2026-10-12T12:00:00.000000Z'


def _digest(value):
    return Digest('sha256', hashlib.sha256(value.encode()).hexdigest())


def _authorization_records(target_ref):
    """Valid typed consent records backed by a declared synthetic fixture."""
    method = MethodRef('fixture-method', '1.0.0', 1, _digest('method'))
    target = Target('primary', target_ref)
    requirement = ReviewRequirement(
        SCOPE, 'acceptance-review', 1, 'acceptance', TargetSet((target,)), method,
        CriterionSetRef('acceptance-criteria', 1, _digest('criteria')),
        (CheckKey(target, 'acceptance-check'),), ('fixture-reviewer',), 'acceptance-phase')
    policy = ConsentPolicyRef('fixture-policy', 1, _digest('policy'))
    source = ConversationSource('synthetic acceptance fixture', (),
        'No real human identity or authorization is represented.', 'fixture-attestor', NOW)
    notice = ConversationNotice(SCOPE, 'acceptance-notice', (target_ref,), target_ref,
        'Synthetic exact artifact acceptance notice.', source, policy)
    intent = AuthorizationIntent(SCOPE, 'acceptance-intent', (target_ref,), method,
        notice.ref, policy, (requirement,), 'reference', 'Synthetic exact acceptance request.',
        NOW, LATER)
    evidence = ConversationEvidence('acceptance-evidence', 'Synthetic confirmation question',
        'Synthetic scope context.', 'Synthetic fixture answer.', source, policy, intent.digest,
        notice.ref, 'confirm')
    challenge = ConsentChallenge(SCOPE, 'acceptance-challenge', intent.intent_id,
        intent.digest, notice.digest, _digest('nonce'), intent.expires_at)
    grant = ApprovalGrant('acceptance-approval', intent, challenge.challenge_id, evidence, NOW)
    return intent, notice, challenge, evidence, grant


def _artifact_graph(factory, artifact_id='accepted-artifact'):
    """Persist an actual schema2 material graph; caller controls branch heads."""
    refs = {}
    with factory.begin(SCOPE) as uow:
        uow.engineering.create(Artifact(SCOPE, artifact_id, 'plan', NOW))
        parent = None
        version = 0
        for revision_id in ('root', 'accepted', 'competing'):
            revision = ArtifactRevision(SCOPE, artifact_id, f'{artifact_id}-{revision_id}', NOW,
                ActorRef('fixture-actor', 'service', 'schema14-test'),
                InlinePayload.from_value('application/json', 'urn:test:acceptance', {'revision': revision_id}),
                () if parent is None or revision_id == 'competing' else (parent,), schema_version=2)
            verify_material(revision, uow.engineering.validated_budget())
            refs[revision_id] = uow.engineering.append_revision(revision, expected_version=version)
            version += 1
            parent = refs[revision_id]
        setup = AcceptancePlan(SCOPE, SubmissionRef(SCOPE.realm_id,SCOPE.project_id,
            f'{artifact_id}-fixture',_digest(f'{artifact_id}-fixture')), 'adopt_content',
            (AcceptanceTarget(refs['competing'], HeadExpectation(artifact_id,3,None)),))
        uow.engineering.apply_acceptance_plan(setup)
        uow.commit()
    return refs


def _insert_storage_fixture(library):
    """Create storage-shaped rows, explicitly not valid decoded consent DTOs."""
    with library.transaction() as connection:
        connection.execute("INSERT INTO eng_notices VALUES (?,?,?,?,?)",
                           (SCOPE.realm_id, SCOPE.project_id, 'notice', 'n-digest', b'{}'))
        connection.execute("INSERT INTO eng_authorization_intents VALUES (?,?,?,?,?,?,?)",
                           (SCOPE.realm_id, SCOPE.project_id, 'intent', 'i-digest', 'notice', 'method', b'{}'))
        connection.execute("INSERT INTO eng_consent_challenges VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                           (SCOPE.realm_id, SCOPE.project_id, 'challenge', 'intent', 'i-digest', 'n-digest',
                            'nonce', 'pending', 0, '2026-10-12T00:00:00.000000Z', b'{}'))
        connection.execute("INSERT INTO eng_approval_grants VALUES (?,?,?,?,?,?,?,?)",
                           (SCOPE.realm_id, SCOPE.project_id, 'approval', 'intent', 'g-digest',
                            'challenge', 'fixture', b'{}'))
        connection.execute("INSERT INTO eng_action_consumptions VALUES (?,?,?,?,?,?,?,?)",
                           (SCOPE.realm_id, SCOPE.project_id, 'old-action', 'approval', 'apply_change',
                            'old-intent', 'old-target', '2026-10-11T00:00:00.000000Z'))
        connection.execute("INSERT INTO eng_apply_records VALUES (?,?,?,?,?,?,?)",
                           (SCOPE.realm_id, SCOPE.project_id, 'apply', 'old-action', 'approval', 'old-target', b'{}'))


def test_schema14_is_explicit_and_default_remains_schema2(tmp_path):
    default = EngineeringLibrary.create((tmp_path / 'default.sqlite').resolve(), library_id='default')
    try:
        assert default._schema_version == 2
    finally:
        default.close()

    library = EngineeringLibrary.create((tmp_path / 'v14.sqlite').resolve(), library_id='v14', schema_version=14)
    try:
        assert library._schema_version == 14
        assert library._connection.execute('PRAGMA foreign_key_check').fetchall() == []
        assert {'eng_action_consumptions', 'eng_acceptance_receipts'} <= {
            row[0] for row in library._connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        sql = library._connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='eng_action_consumptions'").fetchone()[0]
        assert 'accept_artifact' in sql
        assert {'eng_acceptance_receipts_bound_insert', 'eng_acceptance_receipts_no_update',
                'eng_acceptance_receipts_no_delete'} <= {row[0] for row in library._connection.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'")}
    finally:
        library.close()


def test_explicit_13_to_14_upgrade_preserves_action_and_apply_rows_and_uow_owner(tmp_path):
    path = (tmp_path / 'source.sqlite').resolve()
    backup = (tmp_path / 'source.backup.sqlite').resolve()
    library = EngineeringLibrary.create(path, library_id='upgrade', schema_version=13)
    try:
        _insert_storage_fixture(library)
        old_actions = tuple(library._connection.execute('SELECT * FROM eng_action_consumptions'))
        old_apply = tuple(library._connection.execute('SELECT * FROM eng_apply_records'))
        with SQLiteUoWFactory(library).begin(SCOPE, 'read') as uow:
            with pytest.raises(ApplicationError, match='ACCEPTANCE_SCHEMA_REQUIRED'):
                uow.acceptance

        receipt = migrate_schema13(library, backup_path=backup)
        assert receipt.target_version == 14
        assert library._schema_version == 14
        assert tuple(library._connection.execute('SELECT * FROM eng_action_consumptions')) == old_actions
        assert tuple(library._connection.execute('SELECT * FROM eng_apply_records')) == old_apply
        assert library._connection.execute('PRAGMA foreign_key_check').fetchall() == []
        assert 'eng_action_consumptions_upgrade' not in {
            row[0] for row in library._connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        with library.transaction() as connection:
            connection.execute("INSERT INTO eng_action_consumptions VALUES (?,?,?,?,?,?,?,?)",
                (SCOPE.realm_id, SCOPE.project_id, 'accepted-action', 'approval', 'accept_artifact',
                 'accepted-intent', 'accepted-plan', '2026-10-11T00:01:00.000000Z'))
        with SQLiteUoWFactory(library).begin(SCOPE, 'read') as uow:
            assert uow.acceptance is not None
    finally:
        library.close()

    historical = EngineeringLibrary.open(backup, library_id='upgrade')
    try:
        assert historical._schema_version == 13
        assert tuple(historical._connection.execute('SELECT * FROM eng_action_consumptions')) == old_actions
        with pytest.raises(sqlite3.IntegrityError):
            with historical.transaction() as connection:
                connection.execute("INSERT INTO eng_action_consumptions VALUES (?,?,?,?,?,?,?,?)",
                    (SCOPE.realm_id, SCOPE.project_id, 'not-allowed', 'approval', 'accept_artifact',
                     'intent', 'target', '2026-10-11T00:02:00.000000Z'))
    finally:
        historical.close()


def test_receipt_table_requires_matching_original_acceptance_debit_and_is_immutable(tmp_path):
    library = EngineeringLibrary.create((tmp_path / 'v14.sqlite').resolve(), library_id='receipt', schema_version=14)
    try:
        _insert_storage_fixture(library)
        with library.transaction() as connection:
            connection.execute("INSERT INTO eng_action_consumptions VALUES (?,?,?,?,?,?,?,?)",
                (SCOPE.realm_id, SCOPE.project_id, 'accept-action', 'approval', 'accept_artifact',
                 'intent-digest', 'plan-digest', '2026-10-11T00:01:00.000000Z'))
            values = (SCOPE.realm_id, SCOPE.project_id, 'adoption', 'accept-action', 'approval',
                      'intent-digest', 'plan-digest', 'receipt-digest', b'fixture')
            with pytest.raises(sqlite3.IntegrityError, match='ACCEPTANCE_ACTION_BINDING_INVALID'):
                connection.execute('INSERT INTO eng_acceptance_receipts VALUES (?,?,?,?,?,?,?,?,?)',
                                   values[:6] + ('wrong-plan',) + values[7:])
            connection.execute('INSERT INTO eng_acceptance_receipts VALUES (?,?,?,?,?,?,?,?,?)', values)
        with pytest.raises(sqlite3.IntegrityError, match='IMMUTABLE_RECORD'):
            with library.transaction() as connection:
                connection.execute("UPDATE eng_acceptance_receipts SET receipt_digest='changed' WHERE adoption_id='adoption'")
        with pytest.raises(sqlite3.IntegrityError, match='IMMUTABLE_RECORD'):
            with library.transaction() as connection:
                connection.execute("DELETE FROM eng_acceptance_receipts WHERE adoption_id='adoption'")
        with SQLiteUoWFactory(library).begin(SCOPE, 'read') as uow:
            with pytest.raises(ApplicationError, match='NOT_FOUND'):
                uow.acceptance.resolve('unknown-adoption')
    finally:
        library.close()


def test_acceptance_reference_and_adopt_content_have_distinct_head_effects(tmp_path):
    library = EngineeringLibrary.create((tmp_path / 'heads.sqlite').resolve(), library_id='heads', schema_version=14)
    try:
        factory = SQLiteUoWFactory(library)
        refs = _artifact_graph(factory)
        target_head = refs['competing']
        reference = AcceptancePlan(SCOPE, SubmissionRef(SCOPE.realm_id, SCOPE.project_id,
            'submission-reference', _digest('submission-reference')), 'reference',
            (AcceptanceTarget(refs['root'], HeadExpectation('accepted-artifact', 4, target_head)),))
        with factory.begin(SCOPE) as uow:
            assert uow.engineering.apply_acceptance_plan(reference) == (refs['root'],)
            artifact = uow.engineering.get_artifact('accepted-artifact')
            assert (artifact.head_revision_id, artifact.version) == (target_head.revision_id, 4)
            uow.commit()

        adopt = AcceptancePlan(SCOPE, SubmissionRef(SCOPE.realm_id, SCOPE.project_id,
            'submission-adopt', _digest('submission-adopt')), 'adopt_content',
            (AcceptanceTarget(target_head, HeadExpectation('accepted-artifact', 4, target_head)),))
        with factory.begin(SCOPE) as uow:
            assert uow.engineering.apply_acceptance_plan(adopt) == (target_head,)
            artifact = uow.engineering.get_artifact('accepted-artifact')
            assert (artifact.head_revision_id, artifact.version) == (target_head.revision_id, 5)
            uow.commit()
    finally:
        library.close()


def test_acceptance_rejects_wrong_ancestor_stale_version_and_batch_failure_is_atomic(tmp_path):
    library = EngineeringLibrary.create((tmp_path / 'cas.sqlite').resolve(), library_id='cas', schema_version=14)
    try:
        factory = SQLiteUoWFactory(library)
        first = _artifact_graph(factory, 'artifact-one')
        second = _artifact_graph(factory, 'artifact-two')
        current_one, current_two = first['competing'], second['competing']
        stale = AcceptancePlan(SCOPE, SubmissionRef(SCOPE.realm_id, SCOPE.project_id,
            'submission-stale', _digest('submission-stale')), 'reference',
            (AcceptanceTarget(current_one, HeadExpectation('artifact-one', 3, current_one)),))
        wrong_ancestor = AcceptancePlan(SCOPE, SubmissionRef(SCOPE.realm_id, SCOPE.project_id,
            'submission-branch', _digest('submission-branch')), 'adopt_content',
            (AcceptanceTarget(second['accepted'], HeadExpectation('artifact-two', 4, current_two)),))
        batch = AcceptancePlan(SCOPE, SubmissionRef(SCOPE.realm_id, SCOPE.project_id,
            'submission-batch', _digest('submission-batch')), 'adopt_content', (
                AcceptanceTarget(current_one, HeadExpectation('artifact-one', 4, current_one)),
                AcceptanceTarget(second['accepted'], HeadExpectation('artifact-two', 4, current_two)),
            ))
        with factory.begin(SCOPE) as uow:
            with pytest.raises(ApplicationError, match='VERSION_CONFLICT'):
                uow.engineering.apply_acceptance_plan(stale)
            with pytest.raises(ApplicationError, match='ACCEPTANCE_TARGET_NOT_DESCENDANT'):
                uow.engineering.apply_acceptance_plan(wrong_ancestor)
            before = tuple((name, uow.engineering.get_artifact(name).head_revision_id,
                            uow.engineering.get_artifact(name).version)
                           for name in ('artifact-one', 'artifact-two'))
            with pytest.raises(ApplicationError, match='ACCEPTANCE_TARGET_NOT_DESCENDANT'):
                uow.engineering.apply_acceptance_plan(batch)
            after = tuple((name, uow.engineering.get_artifact(name).head_revision_id,
                           uow.engineering.get_artifact(name).version)
                          for name in ('artifact-one', 'artifact-two'))
            assert after == before == (('artifact-one', current_one.revision_id, 4),
                                       ('artifact-two', current_two.revision_id, 4))
            uow.commit()
    finally:
        library.close()


def test_valid_authorization_intent_debit_and_canonical_receipt_same_uow(tmp_path):
    library = EngineeringLibrary.create((tmp_path / 'records.sqlite').resolve(), library_id='records', schema_version=14)
    try:
        factory = SQLiteUoWFactory(library)
        target_ref = ArtifactRevisionRef(SCOPE.realm_id, SCOPE.project_id, 'artifact', 'revision', _digest('revision'))
        intent, notice, challenge, evidence, grant = _authorization_records(target_ref)
        submission_ref = SubmissionRef(SCOPE.realm_id, SCOPE.project_id, 'submission', _digest('submission'))
        plan = AcceptancePlan(SCOPE, submission_ref, 'reference',
            (AcceptanceTarget(target_ref, HeadExpectation('artifact', 0, None)),))
        review_ref = ReviewRef(SCOPE.realm_id, SCOPE.project_id, 'review', _digest('review'))
        receipt = AcceptanceReceipt(SCOPE, 'adoption', 'acceptance-action', grant.ref,
            intent.digest, plan, (review_ref,), 0, NOW)

        with factory.begin(SCOPE) as uow:
            auth = uow.authorization
            auth.put_notice(notice)
            auth.put_intent(intent)
            auth.put_challenge(challenge)
            assert auth.put_receipt(challenge, evidence)
            auth.put_grant(grant)
            with pytest.raises(ApplicationError, match='ACTION_NOT_AUTHORIZED'):
                auth.consume_action(grant.ref, action='apply_change', action_instance_id='wrong-action',
                                   target_digest=plan.digest, now=NOW)
            with pytest.raises(ApplicationError, match='ACTION_NOT_AUTHORIZED'):
                auth.consume_action(grant.ref, action='accept_artifact', action_instance_id='wrong-target-type',
                                   target_digest=None, now=NOW)
            auth.consume_action(grant.ref, action='accept_artifact', action_instance_id='acceptance-action',
                                target_digest=plan.digest, now=NOW)
            receipt_ref = uow.acceptance.create(receipt)
            assert receipt_ref == receipt.ref
            stored = uow.acceptance.resolve('adoption')
            assert stored == receipt
            raw = encode_acceptance_receipt(stored)
            assert decode_acceptance_receipt(raw) == receipt
            assert raw == encode_acceptance_receipt(receipt)
            uow.commit()
    finally:
        library.close()


def test_acceptance_repository_refuses_receipt_without_original_debit(tmp_path):
    library = EngineeringLibrary.create((tmp_path / 'no-debit.sqlite').resolve(), library_id='no-debit', schema_version=14)
    try:
        target_ref = ArtifactRevisionRef(SCOPE.realm_id, SCOPE.project_id, 'artifact', 'revision', _digest('revision'))
        intent, _notice, _challenge, _evidence, grant = _authorization_records(target_ref)
        plan = AcceptancePlan(SCOPE, SubmissionRef(SCOPE.realm_id, SCOPE.project_id,
            'submission-no-debit', _digest('submission-no-debit')), 'reference',
            (AcceptanceTarget(target_ref, HeadExpectation('artifact', 0, None)),))
        receipt = AcceptanceReceipt(SCOPE, 'adoption-no-debit', 'missing-debit-action', grant.ref,
            intent.digest, plan,
            (ReviewRef(SCOPE.realm_id, SCOPE.project_id, 'review', _digest('review')),), 0, NOW)
        with SQLiteUoWFactory(library).begin(SCOPE) as uow:
            with pytest.raises(ApplicationError, match='ACCEPTANCE_ACTION_BINDING_INVALID'):
                uow.acceptance.create(receipt)
    finally:
        library.close()
