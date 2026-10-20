"""Declarative Work on a real 2.7.2 declaration: create, read, associate, refuse.

Nothing here uses a synthetic compiled program: the fixture publishes the real
candidate package and enables its control through the original commands. The
Work row is a context record, so no run, step, dispatch or project file is
touched by creating or reading it.
"""
import asyncio
import hashlib
import pathlib
import sqlite3
from dataclasses import asdict

import pytest
from work_step_access_fixture import enable_controlled_work_steps


@pytest.fixture(autouse=True)
def controlled_work_step_admission(monkeypatch):
    enable_controlled_work_steps(monkeypatch)

from test_itemized_source_chain import build_itemized_chain
from test_real_source_chain import (AUTHOR, NOW, PRINCIPAL, SCOPE, close_chain, context,
                                    create_proposal)
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.application.contracts.commands import CommandKey
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.application.contracts.commands import CommandContext
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.reviews.codec import encode_plan
from ordessa_infrastructure.encoding import decode_json
from ordessa_engineering.application.contracts.work_context import (
    WORK_CONTEXT_KIND, WORK_STABLE_ID_PREFIX, decode_work_binding)
from ordessa_engineering.domain.common.models.identity import Scope

WORK_ID = 'declarative-work-1'


def method_ref_json(ref):
    return {'method_id': ref.method_id, 'release_version': ref.release_version,
            'schema_version': ref.schema_version,
            'snapshot_digest': {'algorithm': 'sha256', 'hex': ref.snapshot_digest.hex}}


def start_params(env, *, work_id=WORK_ID, revision=1, associations=()):
    return {'work_id': work_id, 'revision': revision, 'method_ref': method_ref_json(env.method),
            'associations': [{'kind': kind, 'ref': asdict(ref)} for kind, ref in associations]}


def tree_digest(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob('*')) if path.is_file()}


def open_work(env, params=None, request_id='declarative-work-open'):
    return asyncio.run(env.service.execute('engineering.work.start',
        params or start_params(env), context(request_id)))


def read_work(env, work_id=WORK_ID, request_id='declarative-work-get'):
    return asyncio.run(env.service.query('engineering.work.get', {'work_id': work_id},
                                         context(request_id)))


def test_real_declaration_opens_a_work_and_reads_it_back(tmp_path):
    env = build_itemized_chain(tmp_path)
    try:
        created = open_work(env)
        assert created.status == 'completed', created.result
        assert created.result['release_version'] == '2.7.2'
        assert created.result['associations'] == 0
        view = read_work(env)
        assert view['contract'] == 'ordessa.engineering.declarative-work/1'
        assert (view['work_id'], view['revision']) == (WORK_ID, 1)
        assert view['method_ref']['release_version'] == '2.7.2'
        assert view['method_ref']['schema_version'] == 2
        assert view['digest'] == created.result['material_digest']
        assert view['method_control'] == {'enabled': True, 'version': 1,
                                         'declaration_schema_version': 2}
    finally:
        close_chain(env)


def test_work_row_reopens_at_the_same_revision(tmp_path):
    env = build_itemized_chain(tmp_path)
    try:
        assert open_work(env).status == 'completed'
        library_path = pathlib.Path(env.library.path)
    finally:
        close_chain(env)
    library = EngineeringLibrary.open(library_path, library_id='local-source-chain')
    head = library.head(WORK_CONTEXT_KIND, f'{WORK_STABLE_ID_PREFIX}{WORK_ID}')
    assert head is not None, 'the Work row must survive reopening the library'
    assert head.revision == 1
    binding = decode_work_binding(library.read(head))
    assert (binding.work_id, binding.revision) == (WORK_ID, 1)
    assert binding.method_ref.release_version == '2.7.2'
    assert binding.method_ref.schema_version == 2


def test_work_associates_an_owner_record_without_touching_project_files(tmp_path):
    env = build_itemized_chain(tmp_path)
    try:
        proposal = create_proposal(env)
        project = tmp_path / 'caller-files'
        before = tree_digest(project)
        created = open_work(env, start_params(env, associations=(('proposal', proposal),)),
                            'declarative-work-associate')
        assert created.status == 'completed', created.result
        assert created.result['associations'] == 1
        view = read_work(env, request_id='declarative-work-associated')
        assert [item['kind'] for item in view['associations']] == ['proposal']
        assert view['associations'][0]['ref'] == asdict(proposal)
        assert tree_digest(project) == before, 'associating a record never edits project files'
    finally:
        close_chain(env)


def test_failures_stay_explicit(tmp_path):
    env = build_itemized_chain(tmp_path)
    try:
        params = start_params(env)
        assert open_work(env, params, 'open-idempotent').status == 'completed'
        assert open_work(env, params, 'open-idempotent').status == 'completed'
        with pytest.raises(ApplicationError) as stale:
            open_work(env, params, 'open-other-request')
        assert stale.value.code == 'WORK_REVISION_STALE'
        outsider = CommandContext(Scope(SCOPE.realm_id, 'other-caller-project'), PRINCIPAL,
                                  AUTHOR, 'outsider-open', NOW, 'source-chain-test')
        with pytest.raises(ApplicationError) as denied_write:
            asyncio.run(env.service.execute('engineering.work.start',
                start_params(env, work_id='declarative-work-2'), outsider))
        assert denied_write.value.code in ('ACCESS_DENIED', 'SCOPE_MISMATCH')
        with pytest.raises(ApplicationError) as denied_read:
            asyncio.run(env.service.query('engineering.work.get', {'work_id': WORK_ID}, outsider))
        assert denied_read.value.code in ('ACCESS_DENIED', 'SCOPE_MISMATCH')
        unknown = {**start_params(env, work_id='declarative-work-3'),
                   'method_ref': {**method_ref_json(env.method), 'release_version': '9.9.9'}}
        with pytest.raises(ApplicationError) as invalid_method:
            open_work(env, unknown, 'open-unknown-release')
        assert invalid_method.value.code in ('METHOD_STATE_CORRUPT', 'METHOD_CONTROL_UNAVAILABLE')
        env.management.control(env.method, context('disable-declaration'), expected_version=1,
                               enabled=False, reason='controlled revocation check')
        assert read_work(env, request_id='read-after-disable')['method_control'] == {
            'enabled': False, 'reason': 'METHOD_DISABLED'}
        with pytest.raises(ApplicationError) as disabled:
            open_work(env, start_params(env, work_id='declarative-work-4'), 'open-disabled')
        assert disabled.value.code == 'METHOD_DISABLED'
    finally:
        close_chain(env)


def test_same_request_identity_with_different_content_is_refused(tmp_path):
    """The command journal must answer the first request, never re-interpret a second."""
    env = build_itemized_chain(tmp_path)
    try:
        assert open_work(env, request_id='open-identity').status == 'completed'
        with pytest.raises(ApplicationError) as conflict:
            open_work(env, start_params(env, work_id='declarative-work-9'), 'open-identity')
        assert conflict.value.code == 'REQUEST_IDENTITY_CONFLICT'
        with pytest.raises(ApplicationError) as missing:
            read_work(env, work_id='declarative-work-9', request_id='read-second-work')
        assert missing.value.code == 'WORK_NOT_FOUND'
        assert read_work(env, request_id='read-first-work')['revision'] == 1
    finally:
        close_chain(env)


def test_create_and_read_leave_no_run_or_project_side_effects(tmp_path):
    env = build_itemized_chain(tmp_path)
    try:
        project = tmp_path / 'caller-files'
        before = tree_digest(project)
        assert open_work(env, request_id='open-no-side-effect').status == 'completed'
        read_work(env, request_id='read-no-side-effect')
        after = tree_digest(project)
        library_path = pathlib.Path(env.library.path)
    finally:
        close_chain(env)
    assert after == before
    connection = sqlite3.connect(library_path)
    try:
        assert connection.execute('SELECT count(*) FROM runs').fetchone()[0] == 0
        rows = connection.execute(
            "SELECT revision FROM materials WHERE kind=? AND stable_id=?",
            (WORK_CONTEXT_KIND, f'{WORK_STABLE_ID_PREFIX}{WORK_ID}')).fetchall()
        assert rows == [(1,)]
    finally:
        connection.close()


def declared_and_executable(env, request_id='read-actions'):
    return read_work(env, request_id=request_id)


def test_status_separates_declared_actions_from_currently_executable_ones(tmp_path):
    """Declared actions are described; none becomes executable without a mapping."""
    env = build_itemized_chain(tmp_path)
    try:
        open_work(env)
        view = declared_and_executable(env)
        assert view['status'] == 'active'
        declared = view['declared_actions']
        assert [item['action_id'] for item in declared] == [
            'incremental.review-change', 'incremental.prepare-packages',
            'incremental.implement-package']
        review = next(item for item in declared if item['action_id'] == 'incremental.review-change')
        assert [step['name'] for step in review['steps']] == [
            'jev-review-explicit-change', 'record-explicit-review-result',
            'emit-explicitly-registered-change']
        assert {'name': 'caller_review_input', 'value_kind': 'json_object'} in review['inputs']
        statuses = {item['action_id']: item for item in view['actions']}
        assert set(statuses) == {item['action_id'] for item in declared}
        # Real 2.7.2 example: `incremental.review-change` declares three steps and
        # none of them is mapped yet - the review assembly (criteria, prompt,
        # schemas, binding, plan) is not composed, so the action is unsupported
        # and never offered as executable.
        review_status = statuses['incremental.review-change']
        assert review_status['disposition'] == 'unsupported'
        assert review_status['reason'] == 'ACTION_STEP_NOT_MAPPED'
        assert review_status['unmapped_steps'] == (
            'jev-review-explicit-change', 'record-explicit-review-result',
            'emit-explicitly-registered-change')
        for action_id in ('incremental.prepare-packages', 'incremental.implement-package'):
            status = statuses[action_id]
            # Never available while a declared step has no composed mapping.
            assert status['disposition'] == 'unsupported'
            assert status['reason'] == 'ACTION_STEP_NOT_MAPPED'
            assert 'ACTION_STEP_NOT_MAPPED' in status['reasons']
        # prepare-packages: the admission step is implemented as a guard; its
        # native generation step is mapped only when the real dispatch owner is
        # bound, so here it is unmapped rather than unbound.
        assert statuses['incremental.prepare-packages']['unmapped_steps'] == ('prepare-spec-kit-package',)
        assert statuses['incremental.prepare-packages']['unbound_capabilities'] == ()
        # Neither implementation transport nor a real Workspace scope authority
        # is configured. As with generation, do not invent a composed mapping.
        assert statuses['incremental.implement-package']['unbound_capabilities'] == ()
        assert statuses['incremental.prepare-packages']['unmapped_steps'] == ('prepare-spec-kit-package',)
        # The admission guard consumes no capability; the unmapped native step
        # means no dispatch capability is required (or unbound) yet.
        assert statuses['incremental.prepare-packages']['unbound_capabilities'] == ()
        assert set(statuses['incremental.implement-package']['unmapped_steps']) == {
            'implement-approved-package',
            'independently-review-report', 'resolve-one-operation-disposition',
            'record-operation-result'}
        assert statuses['incremental.implement-package']['unbound_capabilities'] == ()
        # Declared inputs are classified, never demanded up front: the Work pins
        # the method and the caller supplies the rest when it invokes.
        by_name = {item['name']: item for item in review_status['inputs']}
        assert by_name['method']['source'] == 'work_bound'
        assert by_name['method']['satisfied'] is True
        for name in ('baseline', 'candidate', 'scope', 'caller_review_input'):
            assert by_name[name]['source'] == 'caller_supplied'
            assert by_name[name]['reason'] == 'provided_at_invoke'
        assert review_status['missing_prerequisites'] == ()
    finally:
        close_chain(env)


def test_disabled_method_makes_every_declared_action_blocked(tmp_path):
    env = build_itemized_chain(tmp_path)
    try:
        open_work(env)
        env.management.control(env.method, context('disable-for-actions'), expected_version=1,
                               enabled=False, reason='controlled revocation check')
        view = declared_and_executable(env, request_id='read-actions-disabled')
        assert view['status'] == 'method_unavailable'
        # A disabled method yields no declaration at all, so nothing is offered
        # for execution; the state is reported instead of hidden.
        assert view['method_control'] == {'enabled': False, 'reason': 'METHOD_DISABLED'}
        assert view['declared_actions'] == () and view['actions'] == ()
    finally:
        close_chain(env)


def test_availability_requires_a_composed_mapping_and_a_bound_capability(tmp_path):
    """The determination rule itself: mapping and binding, then inputs."""
    from dataclasses import replace
    from ordessa_engineering.application.contracts.work_context import (
        WORK_CONTEXT_KIND, WORK_STABLE_ID_PREFIX, decode_work_binding)
    from ordessa_engineering.application.usecases.queries.works import action_disposition
    env = build_itemized_chain(tmp_path)
    try:
        open_work(env)
        guard = SQLiteMethodControl(env.factory, env.snapshots)
        declaration, _ = guard.read_declaration(context('read-rule-declaration'), env.method)
        action = declaration.actions[0]
        head = env.library.head(WORK_CONTEXT_KIND, f'{WORK_STABLE_ID_PREFIX}{WORK_ID}')
        binding = decode_work_binding(env.library.read(head))
        steps_without_inputs = replace(action, inputs=())
        mapped = {step.name: 'engineering.artifacts.create' for step in action.steps}
        available = action_disposition(steps_without_inputs, binding,
            method_ref=binding.method_ref, control_enabled=True, mapped_steps=mapped,
            bound_capabilities={'engineering.artifacts.create'}, execute_permitted=True)
        assert available['disposition'] == 'available' and available['reasons'] == ()
        # Read permission alone never grants availability: execute is separate.
        read_only = action_disposition(steps_without_inputs, binding,
            method_ref=binding.method_ref, control_enabled=True, mapped_steps=mapped,
            bound_capabilities={'engineering.artifacts.create'}, execute_permitted=False)
        assert read_only['disposition'] == 'condition_blocked'
        assert read_only['reason'] == 'ACTION_EXECUTE_NOT_PERMITTED'
        unbound = action_disposition(steps_without_inputs, binding,
            method_ref=binding.method_ref, control_enabled=True, mapped_steps=mapped,
            bound_capabilities=set(), execute_permitted=True)
        assert unbound['disposition'] == 'condition_blocked'
        assert unbound['reason'] == 'CAPABILITY_NOT_BOUND'
        unmapped = action_disposition(steps_without_inputs, binding,
            method_ref=binding.method_ref, control_enabled=True, mapped_steps={},
            bound_capabilities={'engineering.artifacts.create'}, execute_permitted=True)
        assert unmapped['disposition'] == 'unsupported'
        assert unmapped['reason'] == 'ACTION_STEP_NOT_MAPPED'
    finally:
        close_chain(env)


def read_operation(env, request_id, key='operation-view-read'):
    return asyncio.run(env.service.query('engineering.operations.get',
        {'request_id': request_id}, context(key)))


def test_operation_view_reports_state_work_and_business_separately(tmp_path):
    """One journal row answers both questions, and never collapses them."""
    env = build_itemized_chain(tmp_path)
    try:
        open_work(env, request_id='operation-view-open')
        operation = read_operation(env, 'operation-view-open')
        assert operation['state'] == 'completed'
        assert operation['journal_state'] == 'completed'
        assert operation['operation'] == 'engineering.work.start'
        assert operation['work'] == {'work_id': WORK_ID, 'revision': 1,
                                     'method_id': env.method.method_id,
                                     'release_version': '2.7.2'}
        assert operation['business']['material_digest']
        assert operation['retry_allowed'] is False
        # Replaying the same request identity never re-runs the effect.
        assert open_work(env, request_id='operation-view-open').status == 'completed'
        again = read_operation(env, 'operation-view-open', key='operation-view-read-2')
        assert again['operation_id'] == operation['operation_id']
        library_path = pathlib.Path(env.library.path)
    finally:
        close_chain(env)
    connection = sqlite3.connect(library_path)
    try:
        assert connection.execute(
            "SELECT count(*) FROM materials WHERE kind='work-context'").fetchone()[0] == 1
    finally:
        connection.close()
    # The journal row stays readable after reopening the library.
    library = EngineeringLibrary.open(library_path, library_id='local-source-chain')
    try:
        factory = SQLiteUoWFactory(library)
        with factory.begin(SCOPE, 'read') as uow:
            entry = uow.commands.get(CommandKey(SCOPE.realm_id, PRINCIPAL, 'operation-view-open'))
        assert entry.state == 'completed'
        assert entry.operation == 'engineering.work.start'
    finally:
        library.close()


def test_operation_view_refuses_other_scope_and_unknown_only_reconciles(tmp_path):
    env = build_itemized_chain(tmp_path)
    try:
        open_work(env, request_id='operation-scope-open')
        outsider = CommandContext(Scope(SCOPE.realm_id, 'other-caller-project'), PRINCIPAL,
                                  AUTHOR, 'outsider-operation', NOW, 'source-chain-test')
        with pytest.raises(ApplicationError) as denied:
            asyncio.run(env.service.query('engineering.operations.get',
                {'request_id': 'operation-scope-open'}, outsider))
        assert denied.value.code in ('ACCESS_DENIED', 'SCOPE_MISMATCH')
        with pytest.raises(ApplicationError) as missing:
            read_operation(env, 'no-such-request', key='operation-missing')
        assert missing.value.code == 'OPERATION_NOT_FOUND'
        # An un-finished journal row is unknown: reconcile, never blind retry.
        with env.factory.begin(SCOPE) as uow:
            uow.commands.reserve(CommandKey(SCOPE.realm_id, PRINCIPAL, 'operation-pending'),
                project_id=SCOPE.project_id, operation='engineering.work.start',
                operation_id='op-pending-1', request_digest=Digest('sha256', 'ab' * 32))
            uow.commit()
        pending = read_operation(env, 'operation-pending', key='operation-pending-read')
        assert pending['state'] == 'unknown'
        assert pending['unknown_requires_reconciliation'] is True
        assert pending['retry_allowed'] is False
        assert pending['business'] is None
    finally:
        close_chain(env)


def invoke_action(env, *, action_id='incremental.review-change', work_id=WORK_ID,
                  request_id='invoke-review-change', parameters=None, extra=None):
    payload = {'work_id': work_id, 'action_id': action_id,
               'inputs': parameters if parameters is not None else {}}
    if extra:
        payload.update(extra)
    return asyncio.run(env.service.execute('engineering.work.invoke', payload, context(request_id))).result


def test_invoke_refuses_a_caller_selected_command_and_never_runs_a_subset(tmp_path):
    """The caller names the Work and the action, never the command or a subset."""
    env = build_itemized_chain(tmp_path)
    try:
        open_work(env)
        # A caller-selected command is refused before the declaration is even read.
        with pytest.raises(ApplicationError) as selected:
            invoke_action(env, extra={'operation': 'engineering.reviews.request'})
        assert selected.value.code == 'WORK_ACTION_OPERATION_NOT_CALLER_SELECTED'
        with pytest.raises(ApplicationError) as unavailable:
            invoke_action(env)
        assert unavailable.value.code == 'WORK_ACTION_UNAVAILABLE'
        with pytest.raises(ApplicationError) as unknown:
            invoke_action(env, action_id='incremental.no-such-action',
                          request_id='invoke-unknown-action')
        assert unknown.value.code == 'WORK_ACTION_UNKNOWN'
        # No step ran: the Work still holds exactly one context record.
        assert env.library.head('work-context', f'declarative-work:{WORK_ID}').revision == 1
    finally:
        close_chain(env)


def test_declared_chain_carries_step_order_kinds_sources_and_outputs(tmp_path):
    """The chain the runner follows is the released declaration, not a caller list."""
    env = build_itemized_chain(tmp_path)
    try:
        open_work(env)
        view = read_work(env, WORK_ID, request_id='declared-chain-read')
        assert view['revision'] == 1
        action = next(item for item in view['declared_actions']
                      if item['action_id'] == 'incremental.review-change')
        assert [(step['step_id'], step['kind'], step['name']) for step in action['steps']] == [
            ('compare', 'invoke', 'jev-review-explicit-change'),
            ('record', 'record', 'record-explicit-review-result'),
            ('register', 'emit', 'emit-explicitly-registered-change')]
        compare = action['steps'][0]
        assert {item['source_kind'] for item in compare['inputs']} == {'action_input', 'resource'}
        assert {item['source_name'] for item in compare['inputs']
                if item['source_kind'] == 'resource'} == {
            'change-review-criteria', 'source-review-binding', 'change-review-prompt',
            'source-ref-schema', 'scope-schema', 'method-ref-schema',
            'caller-review-input-schema'}
        assert compare['outputs'] == ['review_contract']
        record = action['steps'][1]
        assert [(item['source_kind'], item['source_name'], item['step_id'])
                for item in record['inputs']] == [('step_output', 'review_contract', 'compare')]
        assert record['outputs'] == ['review_record']
    finally:
        close_chain(env)


def test_invoke_request_identity_replays_and_refuses_a_changed_parent_request(tmp_path):
    """Same parent request + same content replays; changed content is refused."""
    from ordessa_infrastructure.encoding import decode_json
    env = build_itemized_chain(tmp_path)
    try:
        open_work(env)
        works = env.service._works
        first = {'work_id': WORK_ID, 'action_id': 'incremental.review-change',
                 'inputs': {'baseline': 'a', 'candidate': 'b'}}
        _value, digest, replay = works.invoke_replay(first, context('invoke-identity'))
        assert replay is None
        operation_id, reserved = works.begin_invoke(context('invoke-identity'), digest)
        assert reserved is None and operation_id
        works.finish_invoke(context('invoke-identity'), operation_id,
                            {'state': 'completed', 'steps': []})
        _value, _digest, replay = works.invoke_replay(first, context('invoke-identity'))
        assert replay is not None and replay.status == 'completed'
        assert decode_json(replay.result_bytes) == {'state': 'completed', 'steps': []}
        changed = dict(first, inputs={'baseline': 'a', 'candidate': 'c'})
        with pytest.raises(ApplicationError) as conflict:
            works.invoke_replay(changed, context('invoke-identity'))
        assert conflict.value.code == 'REQUEST_IDENTITY_CONFLICT'
    finally:
        close_chain(env)


def _with_review_ports(env):
    """Give this Service the two narrow ports the declared review steps need.

    The test supplies them exactly as the composition does: a factory that
    builds the plan for this Work's fixed sources over the existing decision
    bindings, and the existing reviewer source as the native run.
    """
    from dataclasses import asdict
    steps = env.service._review_change_steps
    def plan_factory(context, binding, *, review_id, baseline, candidate):
        assert baseline == env.baseline and candidate == env.candidate, 'exact Work sources'
        return env.bindings.plan(context, review_id)
    steps.plan_factory = plan_factory
    steps.review_run = env.reviewer.run_review
    env.service._work_queries.mapped_steps = env.service._work_step_capabilities()
    return steps


def test_declared_review_change_runs_all_three_steps_in_order(tmp_path):
    """compare -> record -> register through the formal entry, one journal each."""
    from dataclasses import asdict
    from test_real_source_chain import ControlledDecisionProvider, build_local_chain, create_proposal
    # The official 2.7.2 itemized chain: the plan's two review targets are
    # exactly the proposal's baseline/candidate (verified by probe), so the
    # association admission can legitimately accept the successor.
    env = build_itemized_chain(tmp_path)
    try:
        steps = _with_review_ports(env)
        assert steps.runnable
        proposal_ref = create_proposal(env)
        open_work(env, params=start_params(env, associations=(('proposal', proposal_ref),)))
        result = invoke_action(env, parameters={
            'baseline': asdict(env.baseline), 'candidate': asdict(env.candidate),
            'scope': {'realm_id': SCOPE.realm_id, 'project_id': SCOPE.project_id},
            'method': method_ref_json(env.method),
            'caller_review_input': {}})
        assert result['state'] == 'completed', result
        assert result['completed_steps'] == ['compare', 'record', 'register']
        compare, record, register = result['steps']
        assert compare['operation'] == 'engineering.reviews.request'
        assert compare['business']['review_id']
        assert compare['business']['receipt']['run_id']
        assert record['operation'] == 'engineering.reviews.record'
        assert record['business']['verdict'] in ('pass', 'fail', 'unknown')
        assert record['completion_semantics'] == (
            'formal_review_record_persisted_not_implementation_grant')
        assert register['operation'] == 'engineering.proposals.associate_review'
        assert register['business']['proposal_ref']
        # One Work context row: the invoke itself writes no second record.
        assert env.library.head('work-context', f'declarative-work:{WORK_ID}').revision == 1
        # The declared prepare-packages admission reads this formal review.
        guard = env.service._prepare_packages_steps
        from ordessa_engineering.domain.changes.ref_codec import decode_proposal_ref
        reviewed = decode_proposal_ref(register['business']['proposal_ref'])
        next_work = start_params(env, associations=(('proposal', reviewed),))
        next_work['revision'] = 2
        open_work(env, params=next_work, request_id='bind-reviewed-successor')
        binding = env.service._work_queries.read_binding(context('admission-read'), WORK_ID)
        review_ref = record['business']['review_ref']
        guard_inputs = {'review': review_ref, 'baseline': asdict(env.baseline),
                        'candidate': asdict(env.candidate), 'method': method_ref_json(env.method),
                        'scope': asdict(SCOPE)}
        admitted = guard.check_package_admission(context('admission-check'), binding,
                                                 inputs=guard_inputs)
        assert admitted['admitted'] is True and admitted['verdict'] == 'pass'
        assert admitted['admission_checked'][0] == 'same_scope'
        assert admitted['plan_digest']['hex'] == compare['business']['plan_digest']['hex']
        # A review that is not this Work's completed pass is refused, not softened.
        wrong = dict(guard_inputs, review=dict(review_ref, review_id='not-this-work-review'))
        with pytest.raises(ApplicationError):
            guard.check_package_admission(context('admission-refuse'), binding, inputs=wrong)
        with pytest.raises(ApplicationError) as absent:
            guard.check_package_admission(context('admission-missing'), binding, inputs={})
        assert absent.value.code == 'WORK_ACTION_INPUT_MISSING'
    finally:
        close_chain(env)
