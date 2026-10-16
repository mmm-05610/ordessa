"""Dedicated temporary schema12 qualification; no production authorization claim."""
from pathlib import Path
from dataclasses import replace
import runpy
import sqlite3
import pytest

from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.adapters.persistence.sqlite import migrations
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.approvals.consent import ConversationNotice, ConsentChallenge
from ordessa_engineering.domain.approvals.consent_codec import encode_record, decode_record
from ordessa_engineering.domain.approvals.implementation import ImplementationAuthorizationIntent

DOMAIN = Path(__file__).parents[1] / 'domain'


def fixture_grant():
    ns=runpy.run_path(str(DOMAIN/'test_implementation_package_binding.py'))
    intent,grant,*_=ns['_records']()
    notice=ConversationNotice(intent.scope,'synthetic-notice',intent.targets,intent.targets[0],
        'Synthetic storage fixture, not genuine approval.',grant.evidence.source,intent.policy_ref)
    intent=replace(intent,notice_ref=notice.ref)
    evidence=replace(grant.evidence,notice_ref=notice.ref,intent_digest=intent.digest)
    grant=replace(grant,intent=intent,evidence=evidence)
    challenge=ConsentChallenge(intent.scope,grant.challenge_id,intent.intent_id,intent.digest,
        intent.digest,intent.digest,intent.expires_at)
    return ns,intent,grant,notice,challenge


def persist_grant(factory,intent,grant,notice,challenge):
    with factory.begin(intent.scope) as uow:
        auth=uow.authorization
        auth.put_notice(notice);auth.put_intent(intent);auth.put_challenge(challenge)
        assert auth.put_receipt(challenge,grant.evidence)
        auth.put_grant(grant);uow.commit()


def test_implementation_codec_and_original_ledger_budget_rollback_and_revocation(tmp_path):
    ns,intent,grant,notice,challenge=fixture_grant()
    assert decode_record(encode_record(intent),ImplementationAuthorizationIntent)==intent
    lib=EngineeringLibrary.create((tmp_path/'new.sqlite').resolve(),library_id='new',schema_version=12)
    try:
        factory=SQLiteUoWFactory(lib);persist_grant(factory,intent,grant,notice,challenge)
        blobs=SQLiteBlobStore(lib)
        assert blobs.authority_id==factory.authority_id
        with factory.begin(intent.scope) as uow:
            assert uow.authorization.get_intent(intent.intent_id)==intent
            uow.authorization.consume_action(grant.ref,action='generate_package',action_instance_id='rollback',target_digest=intent.digest,now=ns['NOW'])
            # No commit: both row and consumption roll back on original UoW.
        with factory.begin(intent.scope) as uow:
            assert uow.authorization.action_budget(grant.ref)['actions'][0]['consumed']==0
            for i in range(2):
                uow.authorization.consume_action(grant.ref,action='generate_package',action_instance_id='action-'+str(i),target_digest=intent.digest,now=ns['NOW'])
            uow.commit()
        with factory.begin(intent.scope) as uow:
            with pytest.raises(ApplicationError,match='ACTION_BUDGET_EXHAUSTED'):
                uow.authorization.consume_action(grant.ref,action='generate_package',action_instance_id='overflow',target_digest=intent.digest,now=ns['NOW'])
        with factory.begin(intent.scope) as uow:
            uow.authorization.revoke(grant.ref,expected_version=0,occurred_at=ns['NOW'],reason='fixture revocation',event_id='revoke-event');uow.commit()
        with factory.begin(intent.scope) as uow:
            with pytest.raises(ApplicationError,match='AUTHORIZATION_REVOKED'):
                uow.authorization.consume_action(grant.ref,action='edit_repository',action_instance_id='after-revoke',target_digest=intent.digest,now=ns['NOW'])
    finally:lib.close()


def test_explicit_upgrade_preserves_original_rows_fk_and_backup(tmp_path):
    path=(tmp_path/'old.sqlite').resolve();backup=(tmp_path/'backup.sqlite').resolve()
    lib=EngineeringLibrary.create(path,library_id='migration',schema_version=11)
    try:
        lib.import_material(kind='method',stable_id='legacy',body={'text':'exact\r\nhistory'})
        before=tuple(lib._connection.execute('SELECT * FROM materials'))
        with lib.transaction() as con:
            # Storage/FK fixture only: no application considers these bytes a Grant.
            con.execute("INSERT INTO eng_notices VALUES ('r','p','n','d',?)",(b'{}',))
            con.execute("INSERT INTO eng_authorization_intents VALUES ('r','p','i','d','n','m',?)",(b'{}',))
            con.execute("INSERT INTO eng_consent_challenges VALUES ('r','p','c','i','d','d','nonce','pending',0,'2026-10-12T00:00:00.000000Z',?)",(b'{}',))
            con.execute("INSERT INTO eng_approval_grants VALUES ('r','p','g','i','d','c','fixture',?)",(b'{}',))
            con.execute("INSERT INTO eng_action_consumptions VALUES ('r','p','a','g','apply_change','d','t','2026-10-11T00:00:00.000000Z')")
            con.execute("INSERT INTO eng_apply_records VALUES ('r','p','apply','a','g','d',?)",(b'{}',))
        old_actions=tuple(lib._connection.execute('SELECT * FROM eng_action_consumptions'))
        old_apply=tuple(lib._connection.execute('SELECT * FROM eng_apply_records'))
        receipt=migrations.migrate_schema11(lib,backup_path=backup)
        assert receipt.target_version==12 and lib._schema_version==12
        assert tuple(lib._connection.execute('SELECT * FROM materials'))==before
        assert tuple(lib._connection.execute('SELECT * FROM eng_action_consumptions'))==old_actions
        assert tuple(lib._connection.execute('SELECT * FROM eng_apply_records'))==old_apply
        assert lib._connection.execute('PRAGMA foreign_key_check').fetchall()==[]
        assert 'eng_action_consumptions_upgrade' not in {r[0] for r in lib._connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        with pytest.raises(sqlite3.IntegrityError,match='IMMUTABLE_RECORD'):
            with lib.transaction() as con:con.execute("DELETE FROM eng_action_consumptions")
    finally:lib.close()
    old=EngineeringLibrary.open(backup,library_id='migration')
    try:
        assert old._schema_version==11
        assert tuple(old._connection.execute('SELECT * FROM eng_action_consumptions'))==old_actions
    finally:old.close()
    upgraded=EngineeringLibrary.open(path,library_id='migration');upgraded.close()


def test_submission_original_repository_roundtrip_conflict_and_old_schema_refusal(tmp_path):
    from dataclasses import replace
    record=runpy.run_path(str(DOMAIN/'test_submission.py'))['record']()
    lib=EngineeringLibrary.create((tmp_path/'new.sqlite').resolve(),library_id='facts',schema_version=12)
    try:
        factory=SQLiteUoWFactory(lib)
        with factory.begin(record.scope) as uow:
            assert uow.submissions.create(record)==record.ref
            uow.commit()
        with factory.begin(record.scope) as uow:
            assert uow.submissions.resolve(record.ref)==record
            assert uow.submissions.create(record)==record.ref
            with pytest.raises(ApplicationError,match='SUBMISSION_IDENTITY_CONFLICT'):
                uow.submissions.create(replace(record,checkpoint_ref=record.execution_ref.captured_observation_ref))
    finally:lib.close()
    lib=EngineeringLibrary.create((tmp_path/'old.sqlite').resolve(),library_id='old',schema_version=11)
    try:
        with SQLiteUoWFactory(lib).begin(record.scope,'read') as uow:
            with pytest.raises(ApplicationError,match='SUBMISSION_SCHEMA_REQUIRED'):
                uow.submissions.resolve(record.ref)
    finally:lib.close()
