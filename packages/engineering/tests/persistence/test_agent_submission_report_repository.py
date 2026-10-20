"""Agent rows share original scoped Submission keys; no application COMMIT claim."""
from dataclasses import replace
import hashlib
from pathlib import Path
import runpy

import pytest

from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.changes.submission import SubmissionCoverage
from ordessa_engineering.domain.changes.submission_codec import encode_submission
from ordessa_engineering.domain.common.models.identity import Scope

DOMAIN = Path(__file__).parents[1] / 'domain'


def records():
    agent, _, _ = runpy.run_path(str(DOMAIN / 'test_agent_submission_report.py'))['fixture']()
    old = runpy.run_path(str(DOMAIN / 'test_submission.py'))['record']()
    # Reuse the original Unit reference and schema2 report construction, with
    # its own scope/method/approval; no Agent identity is substituted into it.
    coverage = SubmissionCoverage(old.change_set.proposal_refs[0], agent.output_refs, (), (), 'implemented')
    old_report = replace(old, submission_id='historical-unit-report', baseline_snapshots=(),
        test_evidence=(), effect_observations=(), output_refs=agent.output_refs,
        coverage=(coverage,), method_content=agent.method_content, schema_version=2)
    return old, old_report, agent


def test_original_unit_schema2_golden_bytes_are_unchanged():
    _, old_report, _ = records()
    assert hashlib.sha256(encode_submission(old_report)).hexdigest() == (
        '4ecb61b032581dbc529edad1416dfd9cb1aafbd68e8d5435973d7e708462c49a')


def test_new_agent_data_never_enters_old_report_request_or_acceptance_paths(tmp_path):
    from ordessa_engineering.application.usecases.changes.submissions import SubmissionUseCases
    from ordessa_engineering.application.usecases.changes.acceptance_closure import resolve_submission_acceptance

    old, old_report, agent = records()
    from types import SimpleNamespace
    from ordessa_engineering.application.contracts.commands import CommandContext
    from ordessa_engineering.application.contracts.submissions import agent_report_input_schema, report_input_schema
    context = CommandContext(agent.scope, 'synthetic-principal', agent.created_by,
        'new-agent-data', agent.created_at, 'synthetic-trace')
    assert agent_report_input_schema()['$id'].endswith(':input:2')
    assert report_input_schema(2)['$id'].endswith(':input:1')
    assert SubmissionUseCases.report_request_digest(agent, context) is not None
    # New input2 hashing is data, never admission: without the actual selected
    # source graph the Agent report still cannot reach its business COMMIT.
    usecase = SubmissionUseCases(None, SimpleNamespace(require=lambda *_: None))
    with pytest.raises(ApplicationError, match='SUBMISSION_AGENT_REPORT_SOURCE_UNAVAILABLE'):
        usecase.record_report(agent, context, records=object(), blobs=object(), query_factory=lambda _: None)
    with pytest.raises(ApplicationError, match='SUBMISSION_REPORT_FACT_SHAPE_INVALID'):
        SubmissionUseCases._validate_report_fact_shape(agent)
    library = EngineeringLibrary.create((tmp_path / 'rejected-online.sqlite').resolve(),
        library_id='synthetic-no-online-capture', schema_version=17)
    try:
        factory = SQLiteUoWFactory(library)
        for value in (old_report, agent):
            with factory.begin(value.scope) as uow:
                uow.submissions.create(value)
                uow.commit()
        for value, code in ((old_report, 'SUBMISSION_DECLARED_ACCEPTANCE_UNAVAILABLE'),
                            (agent, 'SUBMISSION_AGENT_ACCEPTANCE_UNAVAILABLE')):
            with factory.begin(value.scope, 'read') as uow:
                with pytest.raises(ApplicationError, match=code):
                    resolve_submission_acceptance(uow, value.ref)
        assert library._connection.execute('SELECT count(*) FROM eng_commands').fetchone() == (0,)
    finally:
        library.close()


def test_original_namespace_and_bytes_coexist_with_tagged_agent_report_and_reopen(tmp_path):
    path = (tmp_path / 'facts.sqlite').resolve()
    old, old_report, agent = records()
    library = EngineeringLibrary.create(path, library_id='synthetic-reports', schema_version=17)
    try:
        factory = SQLiteUoWFactory(library)
        for value in (old, old_report, agent):
            raw = encode_submission(value)
            with factory.begin(value.scope) as uow:
                assert uow.submissions.create(value) == value.ref
                uow.commit()
            row = library._connection.execute(
                'SELECT digest, canonical_bytes FROM eng_submissions WHERE realm_id=? AND project_id=? AND submission_id=?',
                (value.scope.realm_id, value.scope.project_id, value.submission_id)).fetchone()
            assert row == (value.digest.hex, raw)
        with factory.begin(agent.scope) as uow:
            assert uow.submissions.create(agent) == agent.ref
            with pytest.raises(ApplicationError, match='SUBMISSION_IDENTITY_CONFLICT'):
                uow.submissions.create(replace(agent, checkpoint_ref=agent.execution_ref.captured_observation_ref))
        assert library._connection.execute('SELECT count(*) FROM eng_submissions').fetchone() == (3,)
        assert library._connection.execute('PRAGMA foreign_key_check').fetchall() == []
    finally:
        library.close()
    library = EngineeringLibrary.open(path, library_id='synthetic-reports')
    try:
        for value in (old, old_report, agent):
            with SQLiteUoWFactory(library).begin(value.scope, 'read') as uow:
                assert uow.submissions.resolve(value.ref) == value
    finally:
        library.close()


def test_agent_repository_uses_original_scope_readonly_and_schema_fences(tmp_path):
    _, _, agent = records()
    for version in (12, 17):
        library = EngineeringLibrary.create((tmp_path / f'v{version}.sqlite').resolve(),
            library_id=f'synthetic-v{version}', schema_version=version)
        try:
            factory = SQLiteUoWFactory(library)
            with factory.begin(agent.scope) as uow:
                if version == 12:
                    with pytest.raises(ApplicationError, match='WORK_DISPATCH_SCHEMA_REQUIRED'):
                        uow.submissions.create(agent)
                else:
                    uow.submissions.create(agent)
                    uow.commit()
            if version == 17:
                with factory.begin(agent.scope, 'read') as uow:
                    with pytest.raises(ApplicationError): uow.submissions.create(agent)
                with factory.begin(Scope('foreign-realm', agent.scope.project_id)) as uow:
                    with pytest.raises(ApplicationError, match='SCOPE_MISMATCH'): uow.submissions.create(agent)
                    with pytest.raises(ApplicationError, match='SCOPE_MISMATCH'): uow.submissions.resolve(agent.ref)
        finally:
            library.close()


def test_agent_rollback_and_corrupt_canonical_payload_never_resolve(tmp_path):
    _, _, agent = records()
    library = EngineeringLibrary.create((tmp_path / 'corrupt.sqlite').resolve(),
        library_id='synthetic-corruption', schema_version=17)
    try:
        factory = SQLiteUoWFactory(library)
        with factory.begin(agent.scope) as uow:
            uow.submissions.create(agent)
        assert library._connection.execute('SELECT count(*) FROM eng_submissions').fetchone() == (0,)
        # Fresh deliberately corrupt storage fixture, inserted before immutable
        # row triggers: this is not an authorized application report operation.
        with library.transaction() as connection:
            connection.execute('INSERT INTO eng_submissions VALUES (?,?,?,?,?)',
                (agent.scope.realm_id, agent.scope.project_id, agent.submission_id, agent.digest.hex, b'{}'))
        with factory.begin(agent.scope, 'read') as uow:
            with pytest.raises(ApplicationError, match='RECORD_CORRUPT'): uow.submissions.resolve(agent.ref)
    finally:
        library.close()
