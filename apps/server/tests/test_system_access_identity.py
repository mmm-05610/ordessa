"""Real ASGI identity -> original SQLite use case, with explicit test selection.

The test-owned wire descriptor does not assert a production capability catalog,
full CommandReceipt mapper, reviewer trust or the full engineering loop.
"""

import pytest
from fastapi.testclient import TestClient

from ordessa_server.composition.runtime import build_runtime
from ordessa_interfaces.http import create_app
from ordessa_system_access_bindings import EngineeringCommandAccess
from server_plugin_api.wire_errors import WireError
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_interfaces.system_access.access_control.authentication import AccessError, AccessGrant
from server_plugin_api import ServerMethodDescriptor
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.application.usecases.artifacts import ArtifactUseCases
from ordessa_engineering.application.contracts.errors import ApplicationError

OPERATION = 'engineering.artifacts.create'
SCOPE = Scope('test-asgi-realm', 'test-asgi-project')


@pytest.fixture
def selected_runtime(tmp_path):
    runtime = build_runtime(tmp_path / 'server', server_plugins=[])
    library = EngineeringLibrary.create((tmp_path / 'engineering.sqlite').resolve(),
                                        library_id='test-asgi-engineering', schema_version=7)
    factory = SQLiteUoWFactory(library)
    authority = runtime.wire.identity_authority
    authority.replace_grants((AccessGrant(SCOPE, (OPERATION,)),))
    access = EngineeringCommandAccess(authority)
    application = ArtifactUseCases(factory, access)
    invoked = []

    def handler(params, caller):
        scope = Scope(**params['scope'])
        with access.admit(caller, scope, OPERATION, request_id=params['requestId'], trace_id='test-asgi') as context:
            invoked.append(context)
            result = application.create(params['parameters'], context)
            return dict(status=result.status, operation_id=result.operation_id, result=result.result)

    runtime.plugin_host.methods.register(ServerMethodDescriptor(
        method_id=OPERATION, required_params=frozenset({'scope', 'requestId', 'parameters'}),
        optional_params=frozenset(), handler=handler, owner='test.identity', contextual=True,
    ))
    try:
        yield runtime, library, access, invoked
    finally:
        runtime.stop()
        library.close()


def _post(client, runtime, *, scope=SCOPE, parameters=None, request_id='stable-command', attempt='attempt1', **extra):
    params = dict(scope=dict(realm_id=scope.realm_id, project_id=scope.project_id),
                  parameters=parameters or {'kind': 'design'}, requestId=request_id, **extra)
    return client.post('/wire/v1/' + OPERATION, headers={'Authorization': 'Bearer ' + runtime.token},
                       json=dict(jsonrpc='2.0', id=attempt, method=OPERATION, params=params))


def test_asgi_machine_identity_reaches_real_uow_and_changed_attempt_replays_one_journal(selected_runtime):
    runtime, library, access, invoked = selected_runtime
    with TestClient(create_app(runtime), base_url='http://127.0.0.1') as client:
        original = _post(client, runtime).json()['result']
        replay = _post(client, runtime, attempt='changed-transport-attempt').json()['result']
        assert replay == original and original['status'] == 'completed'
        assert invoked[0].principal_id == invoked[1].principal_id == 'local'
        assert all(context.authenticated_actor.actor_kind == 'service' for context in invoked)
        assert library._connection.execute('SELECT COUNT(*) FROM eng_artifacts').fetchone() == (1,)
        assert library._connection.execute('SELECT COUNT(*) FROM eng_commands').fetchone() == (1,)
        context = invoked[0]
        with pytest.raises(ApplicationError) as no_lease:
            access.require(context, OPERATION)
        assert no_lease.value.code == 'ACCESS_AUTHORITY_UNAVAILABLE'


@pytest.mark.parametrize('extra', [{'principal_id': 'human'}, {'authenticated_actor': {'actor_kind': 'human'}},
                                   {'verified': True}, {'caller': {'principal_id': 'local'}}])
def test_json_cannot_supply_trusted_caller_or_actor(selected_runtime, extra):
    runtime, library, _access, invoked = selected_runtime
    with TestClient(create_app(runtime), base_url='http://127.0.0.1') as client:
        reply = _post(client, runtime, **extra).json()
        assert reply['error']['code'] == 'INVALID_REQUEST'
        assert invoked == []
        assert library._connection.execute('SELECT COUNT(*) FROM eng_commands').fetchone() == (0,)


def test_cross_project_and_missing_capability_never_create_command(selected_runtime):
    runtime, library, _access, invoked = selected_runtime
    with TestClient(create_app(runtime), base_url='http://127.0.0.1') as client:
        reply = _post(client, runtime, scope=Scope(SCOPE.realm_id, 'foreign')).json()
        assert reply['error']['details']['internalCode'] == 'ACCESS_DENIED'
        runtime.wire.identity_authority.replace_grants(())
        reply = _post(client, runtime).json()
        assert reply['error']['details']['internalCode'] == 'ACCESS_DENIED'
        assert invoked == []
        assert library._connection.execute('SELECT COUNT(*) FROM eng_commands').fetchone() == (0,)


def test_direct_dispatch_requires_issued_identity_and_round_retirement_invalidates_old_caller(selected_runtime):
    runtime, library, _access, invoked = selected_runtime
    runtime.start()
    authority = runtime.wire.identity_authority
    caller = authority.authenticate('Bearer ' + runtime.token)
    params = dict(scope=dict(realm_id=SCOPE.realm_id, project_id=SCOPE.project_id),
                  parameters={'kind': 'design'}, requestId='identity-one')
    for invalid in (None, {'principal_id': 'local'}):
        with pytest.raises(WireError) as refused:
            runtime.wire.dispatch(OPERATION, params, caller=invalid)
        assert refused.value.family == 'UNAUTHENTICATED'
    runtime.wire.dispatch(OPERATION, params, caller=caller)
    runtime.stop()
    with pytest.raises(AccessError) as stale:
        authority.verify(caller)
    assert stale.value.code == 'AUTHORIZATION_STALE'
    runtime.start()
    assert authority.authenticate('Bearer ' + runtime.token).credential_epoch > caller.credential_epoch
    assert library._connection.execute('SELECT COUNT(*) FROM eng_commands').fetchone() == (1,)


def test_revoked_instance_bearer_cannot_reenter_http_even_with_same_header(selected_runtime):
    runtime, library, _access, invoked = selected_runtime
    with TestClient(create_app(runtime), base_url='http://127.0.0.1') as client:
        runtime.wire.identity_authority.revoke()
        response = _post(client, runtime)
        assert response.status_code == 401
        assert response.json()['error']['code'] == 'UNAUTHENTICATED'
        assert invoked == []
        assert library._connection.execute('SELECT COUNT(*) FROM eng_commands').fetchone() == (0,)


def test_copied_context_cannot_reuse_admission_after_exit_or_on_another_thread(selected_runtime):
    from contextvars import copy_context
    from threading import Thread
    runtime, library, access, _invoked = selected_runtime
    caller = runtime.wire.identity_authority.authenticate('Bearer ' + runtime.token)
    failures = []
    with access.admit(caller, SCOPE, OPERATION, request_id='copied-context', trace_id='copied') as context:
        copied = copy_context()
        thread_copy = copy_context()

        def misuse_from_thread():
            try:
                thread_copy.run(access.require, context, OPERATION)
            except ApplicationError as exc:
                failures.append(exc.code)

        worker = Thread(target=misuse_from_thread)
        worker.start()
        worker.join(1)
        assert not worker.is_alive()
        assert failures == ['ACCESS_AUTHORITY_UNAVAILABLE']
        access.require(context, OPERATION)
    application = ArtifactUseCases(SQLiteUoWFactory(library), access)
    with pytest.raises(ApplicationError) as expired:
        copied.run(application.create, {'kind': 'design'}, context)
    assert expired.value.code == 'ACCESS_AUTHORITY_UNAVAILABLE'
    assert library._connection.execute('SELECT COUNT(*) FROM eng_commands').fetchone() == (0,)


def test_real_sqlite_commit_remains_inside_identity_guard(selected_runtime, monkeypatch):
    from threading import Event, Thread
    from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteEngineeringUoW
    runtime, library, _access, _invoked = selected_runtime
    attempted, revoked = Event(), Event()
    workers = []
    original_finish = SQLiteEngineeringUoW._finish

    def finish_with_racing_revocation(self, error=None):
        if error is None:
            def revoke():
                attempted.set()
                runtime.wire.identity_authority.revoke()
                revoked.set()
            worker = Thread(target=revoke)
            workers.append(worker)
            worker.start()
            assert attempted.wait(1)
            assert not revoked.wait(.03)
        result = original_finish(self, error)
        assert not revoked.is_set()
        return result

    monkeypatch.setattr(SQLiteEngineeringUoW, '_finish', finish_with_racing_revocation)
    with TestClient(create_app(runtime), base_url='http://127.0.0.1') as client:
        response = _post(client, runtime)
        assert response.json()['result']['status'] == 'completed'
        assert revoked.wait(1)
        assert library._connection.execute('SELECT COUNT(*) FROM eng_commands').fetchone() == (1,)
        assert library._connection.execute('SELECT COUNT(*) FROM eng_artifacts').fetchone() == (1,)
        assert _post(client, runtime).status_code == 401
    for worker in workers:
        worker.join(1)
        assert not worker.is_alive()


def test_contextual_descriptor_flag_survives_live_rebinding(selected_runtime):
    runtime, _library, _access, _invoked = selected_runtime
    runtime.start()
    runtime.wire.replace_handler(OPERATION, lambda params, caller: caller.principal_id)
    runtime.wire.amend_shape(OPERATION, required=set(), optional=set())
    assert runtime.plugin_host.methods.lookup(OPERATION).contextual is True
    with pytest.raises(WireError) as refused:
        runtime.wire.dispatch(OPERATION, {})
    assert refused.value.family == 'UNAUTHENTICATED'
    caller = runtime.wire.identity_authority.authenticate('Bearer ' + runtime.token)
    assert runtime.wire.dispatch(OPERATION, {}, caller=caller) == 'local'
    with pytest.raises(ValueError):
        ServerMethodDescriptor(method_id='test.invalid-context', required_params=frozenset(),
                               optional_params=frozenset(), handler=lambda params: None,
                               owner='test.identity', contextual='true')
