"""LocalUnitOwner cold receipt queries use its original permission and records."""
from types import SimpleNamespace

import pytest

from ordessa_execution_agents.harness.transport import EffectWriteRefused
from ordessa_units.errors import UnitIdentityMismatch
from ordessa_infrastructure.identifiers import RequestKey
from ordessa_interfaces.system_access.contracts.transport import AccessError
from ordessa_units.admission.invocation import InvocationAuthorityRefused
from ordessa_units.admission.run_permission import RUN_ACTIONS
from ordessa_units.admission.owner_selection import AgentOwnerUnavailable
from ordessa_units.api.unit import Unit

from test_local_owner import Preparation, _materializer, live_owner


def test_local_owner_native_unit_returns_only_exact_live_public_handle(live_owner):
    world = live_owner
    authorization = world.owner.authorization()
    unit = world.public_manager.create(world.owner.spec, authorization)
    instance = world.original_manager.find(unit.identity)
    lease = world.owner.authorize("interaction", unit, authorization)
    assert world.owner.authorize("interaction", unit, authorization) is lease

    connections_before = dict(world.owner._connections)
    assert world.owner.native_unit(unit, authorization) is instance
    assert world.owner._connections == connections_before

    # Unit's public constructor can make a facade around the same identity and
    # underlying instance; only the exact retained view is accepted.
    copied_view = Unit(unit._assembly, unit._instance)
    with pytest.raises(AgentOwnerUnavailable):
        world.owner.native_unit(copied_view, authorization)
    foreign_view = Unit(object(), unit._instance)
    with pytest.raises(AgentOwnerUnavailable):
        world.owner.native_unit(foreign_view, authorization)

    class UnitSubclass(Unit):
        pass

    with pytest.raises(AgentOwnerUnavailable):
        world.owner.native_unit(UnitSubclass(unit._assembly, unit._instance), authorization)

    assert unit.close(authorization)["state"] == "confirmed"
    with pytest.raises(AgentOwnerUnavailable):
        world.owner.native_unit(unit, authorization)


def test_local_owner_native_unit_refuses_expired_permission(live_owner):
    world = live_owner
    authorization = world.owner.authorization()
    unit = world.public_manager.create(world.owner.spec, authorization)
    world.now[0] = world.permission.expires_at + 1
    with pytest.raises(InvocationAuthorityRefused):
        world.owner.native_unit(unit, authorization)


def test_local_owner_native_unit_refuses_stale_environment_generation(live_owner, monkeypatch):
    world = live_owner
    authorization = world.owner.authorization()
    unit = world.public_manager.create(world.owner.spec, authorization)
    snapshot = world.environment.snapshot
    monkeypatch.setattr(world.owner.state, "_snapshot", lambda: SimpleNamespace(
        phase="ready", generation=snapshot.generation + 1,
        observation=SimpleNamespace(state="running")))
    with pytest.raises(AgentOwnerUnavailable):
        world.owner.native_unit(unit, authorization)


@pytest.mark.parametrize("value", [1, None, "true"])
def test_local_owner_acp_opt_in_requires_exact_boolean(live_owner, value):
    world = live_owner
    from ordessa_units.assembly.local_owner import build_local_unit_owner

    with pytest.raises(AgentOwnerUnavailable):
        build_local_unit_owner(
            admission_context=world.admission,
            permission=world.permission,
            environment_instance=world.environment,
            preparation=Preparation(),
            materializer=_materializer,
            environment_sharing=True,
            acp_turn_opt_in=value,
            clock=lambda: world.now[0],
        )
    assert world.environment.snapshot.active_uses == 0


def test_local_owner_query_refuses_without_original_acp_schema_before_reserve(live_owner):
    world = live_owner
    authorization = world.owner.authorization()
    unit = world.public_manager.create(world.owner.spec, authorization)
    request = RequestKey("env", world.permission.principal_scope, "query-without-acp-opt-in")
    assert world.owner.acp_turn_opt_in is False
    assert world.records.acp_turn_available is False
    assert world.records.journal.acp_turn_opt_in is False

    with pytest.raises(InvocationAuthorityRefused):
        world.owner.authorize_acp_turn_query(
            authorization, request, unit.identity, "schema-not-enabled",
            expected_prompt_input_digest="sha256:" + "e" * 64)
    assert world.store.read_operation(request) is None


def test_local_owner_guard_requires_explicit_acp_opt_in(live_owner):
    world = live_owner
    from ordessa_units.assembly.local_owner import build_local_unit_owner

    with pytest.raises(AgentOwnerUnavailable):
        build_local_unit_owner(
            admission_context=world.admission,
            permission=world.permission,
            environment_instance=world.environment,
            preparation=Preparation(),
            materializer=_materializer,
            environment_sharing=True,
            effect_write_guard_factory=lambda *_args: None,
            acp_turn_opt_in=False,
            clock=lambda: world.now[0],
        )
    assert world.environment.snapshot.active_uses == 0


@pytest.mark.parametrize("live_owner", [{"acp_turn_opt_in": True}], indirect=True)
def test_local_owner_issues_read_only_query_after_unit_release(live_owner):
    world = live_owner
    authorization = world.owner.authorization()
    unit = world.public_manager.create(world.owner.spec, authorization)
    unit_ref = unit.identity
    instance = world.original_manager.find(unit_ref)
    lease = world.owner.authorize("interaction", unit, authorization)
    prompt = [{"type": "text", "text": "recorded local receipt"}]
    original = instance.prompt(
        unit_ref, lease, operation_ref="local-recorded-read", timeout=5, prompt=prompt)
    assert original["state"] == "completed"
    assert world.owner.records is world.records
    assert "query" not in RUN_ACTIONS
    assert "query" not in world.permission.actions

    # Release removes the live Unit/EnvironmentUse. A cold read is still
    # authorized by the exact owner permission and immutable original record.
    assert unit.close(authorization)["state"] == "confirmed"
    assert world.environment.snapshot.active_uses == 0
    request = RequestKey("env", world.permission.principal_scope, "local-receipt-query-1")
    invocation = world.owner.authorize_acp_turn_query(
        authorization, request, unit_ref, "local-recorded-read",
        expected_prompt_input_digest=original["inputDigest"])
    query_digest = world.records.acp_turn_query_digest(
        unit_ref, "local-recorded-read", original["inputDigest"])
    receipt = world.records.query_acp_turn(
        unit_ref, "local-recorded-read", invocation,
        input_digest=query_digest, expected_prompt_input_digest=original["inputDigest"])

    assert receipt == original
    assert world.issuer.verified_observation(invocation) is True
    assert world.issuer.verified_consumption(invocation) is False
    with pytest.raises(InvocationAuthorityRefused):
        world.verifier.verify_and_consume(
            invocation, "start", invocation.facts["providerRef"],
            invocation.facts["targetRef"], invocation.facts["inputDigest"])
    assert world.issuer.verified_consumption(invocation) is False
    with pytest.raises(InvocationAuthorityRefused):
        world.verifier.verify_and_consume(
            invocation, "session/prompt", invocation.facts["providerRef"],
            invocation.facts["targetRef"], invocation.facts["inputDigest"])
    assert world.store.read_operation_step(request, "read") is None


@pytest.mark.parametrize("live_owner", [{"acp_turn_opt_in": True}], indirect=True)
def test_local_owner_query_refuses_same_unit_id_with_forged_reference_fields(live_owner):
    world = live_owner
    authorization = world.owner.authorization()
    unit = world.public_manager.create(world.owner.spec, authorization)
    unit_ref = dict(unit.identity)
    incomplete_ref = {"unitId": unit_ref["unitId"]}
    changed_revision = dict(unit_ref)
    changed_revision["sourceRevision"] = unit_ref["sourceRevision"] + ".forged"
    changed_provider = dict(unit_ref)
    changed_provider["ownerProviderRef"] = {"providerId": "forged-provider"}

    for index, forged in enumerate((incomplete_ref, changed_revision, changed_provider)):
        request = RequestKey("env", world.permission.principal_scope,
                             f"local-query-forged-ref-{index}")
        with pytest.raises(InvocationAuthorityRefused):
            world.owner.authorize_acp_turn_query(
                authorization, request, forged, "forged-reference-read",
                expected_prompt_input_digest="sha256:" + "a" * 64)
        assert world.store.read_operation(request) is None


@pytest.mark.parametrize("live_owner", [{"acp_turn_opt_in": True}], indirect=True)
def test_local_owner_query_refuses_wrong_request_namespace_or_principal(live_owner):
    world = live_owner
    authorization = world.owner.authorization()
    unit = world.public_manager.create(world.owner.spec, authorization)
    requests = (
        RequestKey("foreign-env", world.permission.principal_scope, "wrong-query-namespace"),
        RequestKey("env", "foreign-principal", "wrong-query-principal"),
    )
    for request in requests:
        with pytest.raises(InvocationAuthorityRefused):
            world.owner.authorize_acp_turn_query(
                authorization, request, unit.identity, "wrong-request-scope",
                expected_prompt_input_digest="sha256:" + "b" * 64)
        assert world.store.read_operation(request) is None


@pytest.mark.parametrize("changed", ["operation", "input_digest"])
@pytest.mark.parametrize("live_owner", [{"acp_turn_opt_in": True}], indirect=True)
def test_local_owner_query_request_conflict_preserves_original_recipe(live_owner, changed):
    world = live_owner
    authorization = world.owner.authorization()
    unit = world.public_manager.create(world.owner.spec, authorization)
    request = RequestKey("env", world.permission.principal_scope,
                         f"local-query-conflict-{changed}")
    original_digest = "sha256:" + "c" * 64
    original_operation = "stable-query-operation"
    original_ticket = world.owner.authorize_acp_turn_query(
        authorization, request, unit.identity, original_operation,
        expected_prompt_input_digest=original_digest)
    original_record = world.store.read_operation(request)
    assert original_record is not None

    replacement_operation = ("changed-query-operation" if changed == "operation"
                             else original_operation)
    replacement_digest = ("sha256:" + "d" * 64 if changed == "input_digest"
                          else original_digest)
    with pytest.raises(UnitIdentityMismatch):
        world.owner.authorize_acp_turn_query(
            authorization, request, unit.identity, replacement_operation,
            expected_prompt_input_digest=replacement_digest)

    retained_record = world.store.read_operation(request)
    assert retained_record is not None
    assert retained_record.intent == original_record.intent
    assert retained_record.digest == original_record.digest
    # The ticket was issued but no original records reader observed it. The
    # conflicting retry must preserve the frozen recipe without creating a
    # read claim or converting issuance into observation/effect authority.
    assert world.issuer.verified_observation(original_ticket) is False
    assert world.issuer.verified_consumption(original_ticket) is False
    assert world.store.read_operation_step(request, "read") is None


@pytest.mark.parametrize("live_owner", [{"acp_turn_opt_in": True}], indirect=True)
def test_local_owner_query_refuses_expired_permission_before_reserving(live_owner):
    world = live_owner
    authorization = world.owner.authorization()
    unit = world.public_manager.create(world.owner.spec, authorization)
    unit_ref = unit.identity
    instance = world.original_manager.find(unit_ref)
    lease = world.owner.authorize("interaction", unit, authorization)
    original = instance.prompt(
        unit_ref, lease, operation_ref="expire-before-read", timeout=5,
        prompt=[{"type": "text", "text": "bounded fixture"}])
    assert unit.close(authorization)["state"] == "confirmed"

    request = RequestKey("env", world.permission.principal_scope, "local-receipt-expired-1")
    world.now[0] = world.permission.expires_at + 1
    with pytest.raises(InvocationAuthorityRefused):
        world.owner.authorize_acp_turn_query(
            authorization, request, unit_ref, "expire-before-read",
            expected_prompt_input_digest=original["inputDigest"])
    assert world.store.read_operation(request) is None


@pytest.mark.parametrize("live_owner", [{"acp_turn_opt_in": True}], indirect=True)
def test_local_owner_query_refuses_environment_generation_change(live_owner, monkeypatch):
    world = live_owner
    authorization = world.owner.authorization()
    unit = world.public_manager.create(world.owner.spec, authorization)
    unit_ref = unit.identity
    instance = world.original_manager.find(unit_ref)
    lease = world.owner.authorize("interaction", unit, authorization)
    original = instance.prompt(
        unit_ref, lease, operation_ref="generation-bound-read", timeout=5,
        prompt=[{"type": "text", "text": "generation fixture"}])
    assert unit.close(authorization)["state"] == "confirmed"

    old_generation = world.owner.environment.snapshot.generation
    monkeypatch.setattr(world.owner.state, "_snapshot_generation", lambda: SimpleNamespace(
        generation=old_generation + 1))
    request = RequestKey("env", world.permission.principal_scope, "local-receipt-generation-1")
    with pytest.raises(InvocationAuthorityRefused):
        world.owner.authorize_acp_turn_query(
            authorization, request, unit_ref, "generation-bound-read",
            expected_prompt_input_digest=original["inputDigest"])


@pytest.mark.parametrize("live_owner", [{"acp_turn_opt_in": True}], indirect=True)
def test_local_owner_query_refuses_owner_or_access_revocation(live_owner):
    world = live_owner
    authorization = world.owner.authorization()
    unit = world.public_manager.create(world.owner.spec, authorization)
    unit_ref = unit.identity
    instance = world.original_manager.find(unit_ref)
    lease = world.owner.authorize("interaction", unit, authorization)
    original = instance.prompt(
        unit_ref, lease, operation_ref="revoked-before-read", timeout=5,
        prompt=[{"type": "text", "text": "revocation fixture"}])
    assert unit.close(authorization)["state"] == "confirmed"

    request = RequestKey("env", world.permission.principal_scope, "local-receipt-revoked-1")
    with pytest.raises(InvocationAuthorityRefused):
        world.owner.authorize_acp_turn_query(
            object(), request, unit_ref, "revoked-before-read",
            expected_prompt_input_digest=original["inputDigest"])
    world.access.revoke()
    with pytest.raises(AccessError):
        world.owner.authorize_acp_turn_query(
            authorization, request, unit_ref, "revoked-before-read",
            expected_prompt_input_digest=original["inputDigest"])
    assert world.store.read_operation(request) is None
    world.access_revoked_cleanup = True


@pytest.mark.parametrize("live_owner", [{"acp_turn_opt_in": True}], indirect=True)
def test_local_owner_revoke_fences_receipt_query(live_owner):
    world = live_owner
    authorization = world.owner.authorization()
    unit = world.public_manager.create(world.owner.spec, authorization)
    unit_ref = unit.identity
    instance = world.original_manager.find(unit_ref)
    lease = world.owner.authorize("interaction", unit, authorization)
    original = instance.prompt(
        unit_ref, lease, operation_ref="owner-revoked-read", timeout=5,
        prompt=[{"type": "text", "text": "owner revoke fixture"}])
    assert unit.close(authorization)["state"] == "confirmed"
    world.access_revoked_cleanup = True
    world.owner.revoke()
    request = RequestKey("env", world.permission.principal_scope, "local-receipt-owner-revoked-1")
    with pytest.raises(InvocationAuthorityRefused):
        world.owner.authorize_acp_turn_query(
            authorization, request, unit_ref, "owner-revoked-read",
            expected_prompt_input_digest=original["inputDigest"])
    assert world.store.read_operation(request) is None


@pytest.mark.parametrize("live_owner", [{"acp_turn_opt_in": True}], indirect=True)
@pytest.mark.parametrize("revocation", ["host_access", "generation"])
def test_issued_local_query_is_rejected_after_authority_or_generation_changes(
        live_owner, monkeypatch, revocation):
    world = live_owner
    authorization = world.owner.authorization()
    unit = world.public_manager.create(world.owner.spec, authorization)
    unit_ref = unit.identity
    instance = world.original_manager.find(unit_ref)
    lease = world.owner.authorize("interaction", unit, authorization)
    receipt = instance.prompt(
        unit_ref, lease, operation_ref=f"query-after-{revocation}", timeout=5,
        prompt=[{"type": "text", "text": "original receipt"}])
    assert unit.close(authorization)["state"] == "confirmed"

    request = RequestKey("env", world.permission.principal_scope,
                         f"local-query-after-{revocation}")
    operation_ref = f"query-after-{revocation}"
    ticket = world.owner.authorize_acp_turn_query(
        authorization, request, unit_ref, operation_ref,
        expected_prompt_input_digest=receipt["inputDigest"])
    query_digest = world.records.acp_turn_query_digest(
        unit_ref, operation_ref, receipt["inputDigest"])

    if revocation == "host_access":
        world.access.revoke()
        world.access_revoked_cleanup = True
    else:
        old_generation = world.environment.snapshot.generation
        monkeypatch.setattr(world.owner.state, "_snapshot_generation", lambda: SimpleNamespace(
            generation=old_generation + 1))

    with pytest.raises(InvocationAuthorityRefused):
        world.records.query_acp_turn(
            unit_ref, operation_ref, ticket,
            input_digest=query_digest, expected_prompt_input_digest=receipt["inputDigest"])
    assert world.issuer.verified_observation(ticket) is False
    assert world.issuer.verified_consumption(ticket) is False
    assert world.store.read_operation_step(request, "read") is None


@pytest.mark.parametrize("live_owner", [{
    "acp_turn_opt_in": True,
    "effect_write_guard_factory": lambda *_args: None,
}], indirect=True)
def test_local_owner_injects_exact_fixed_effect_guard_before_unit_creation(live_owner):
    world = live_owner
    authorization = world.owner.authorization()
    unit = world.public_manager.create(world.owner.spec, authorization)
    instance = world.original_manager.find(unit.identity)
    assert instance.require_effect_write_guard(world.owner.effect_write_guard_factory) is None
    with pytest.raises(EffectWriteRefused):
        instance.require_effect_write_guard(lambda *_args: None)
    assert unit.close(authorization)["state"] == "confirmed"


def test_local_owner_without_fixed_effect_guard_refuses_guarded_dispatch(live_owner):
    world = live_owner
    authorization = world.owner.authorization()
    unit = world.public_manager.create(world.owner.spec, authorization)
    instance = world.original_manager.find(unit.identity)
    assert world.owner.effect_write_guard_factory is None
    with pytest.raises(EffectWriteRefused):
        instance.require_effect_write_guard(lambda *_args: None)
    assert unit.close(authorization)["state"] == "confirmed"


@pytest.fixture
def historical_query_world(tmp_path):
    """Real stores/access/issuer; explicit seed evidence peers, no native Unit.

    An original reservation/session and UNKNOWN ACP receipt are recorded through
    UnitRecords, then the journal is reopened for new Units. No Manager creates a
    Unit, no process starts, and no model or native channel is consulted.
    """
    import hashlib
    import os
    from ordessa_execution_agents.profiles import encode_revision_ref
    from ordessa_infrastructure.encoding.immutable_json import safe_json
    from ordessa_units.admission.invocation import InvocationIssuer
    from ordessa_units.admission.local_state import FixedUnitCurrentState
    from ordessa_units.admission.run_permission import LocalUnitInvocationAuthority
    from ordessa_units.assembly.local_owner import LocalUnitOwner
    from ordessa_units.definitions.operations import OperationIntent, StepIntent
    from ordessa_units.persistence.sqlite.store import SqliteUnitStore
    from ordessa_units.records import OperationJournal, UnitRecords, UnitRecordsRefused, acp_turns
    from test_local_owner import _access_authority, _run_permission, BEARER

    access = _access_authority()
    principal = access.authenticate('Bearer ' + BEARER)
    old_permission = _run_permission(access, principal, tmp_path / 'units', expires_at=50.0)
    permission = _run_permission(access, principal, tmp_path / 'units', expires_at=100.0)
    environment = SimpleNamespace(identity=permission.environment_identity,
                                  snapshot=SimpleNamespace(generation=1))
    catalog = SimpleNamespace(describe=lambda *_: None)
    store = SqliteUnitStore(tmp_path / 'operations.sqlite')
    def state_for(owner_id, selected_permission):
        return FixedUnitCurrentState(store=store, harness_catalog=catalog,
            environment_instance=environment, environment_namespace='env',
            root_directory=permission.root_directory, owner_id=owner_id,
            profile_revision=permission.profile_revision, agent_id=permission.agent_id,
            permission_id=selected_permission.identity)
    old_state, state = state_for('old-owner', old_permission), state_for('current-owner', permission)
    node = {'environmentNamespace': 'env', 'nodeId': 'original-node', 'generation': 1}
    provider = {'environmentNamespace': 'env', 'providerId': 'controlled-pi', 'generation': 1}
    roots = {k: str(tmp_path / 'units/original-node' / k) for k in ('home', 'cwd', 'profile', 'tmp')}
    request = RequestKey('env', permission.principal_scope, 'original-preparation')
    original_run = {'ownerId': 'old-owner', 'permissionId': old_permission.identity,
        'agentId': permission.agent_id, 'environmentIdentity': environment.identity,
        'environmentGeneration': 1, 'profileRevision': encode_revision_ref(permission.profile_revision)}
    context = {'environmentNamespace': 'env', 'nodeRef': node, 'privateRootFacts': roots,
        'directoryBindingRef': old_state.directory_ref(node, roots).to_dict(),
        'harnessDefinitionRef': {'environmentNamespace': 'env', 'definitionId': 'fixture', 'revision': '1'},
        'localUnitRun': original_run}
    step = StepIntent('prepare', provider, 'prepare-input', 'original-prepare.prepare', management_epoch=1)
    intent = OperationIntent('original-prepare', 'unit-public-prepare',
        encode_revision_ref(permission.profile_revision), context, (step,), node_ref=node, management_epoch=1)
    store.reserve_operation(request, 'prepare-operation-input', intent)

    class SeedVerifier:
        def __init__(self):
            self.issued = {}
        def issue(self, action, digest):
            token = object()
            self.issued[token] = {'query': False, 'action': action, 'providerRef': provider,
                'targetRef': node, 'inputDigest': digest, 'managementEpoch': 1,
                'request': {'environmentNamespace': 'env', 'principalScope': request.principal_scope,
                            'requestId': request.request_id},
                'operationRef': 'original-prepare' if action == 'prepare' else 'original-start',
                'stepId': action}
            return token
        def verify_and_consume(self, token, action, supplied_provider, supplied_node, digest):
            facts = self.issued.pop(token)
            assert (action, supplied_provider, supplied_node, digest) == (
                facts['action'], facts['providerRef'], facts['targetRef'], facts['inputDigest'])
            return facts

    scope_ref = old_state._scope(provider, node, roots)
    scope = SimpleNamespace(issue_scope=lambda *_: scope_ref,
        verify_scope=lambda s, r: s == scope_ref and safe_json(r) == safe_json(roots),
        map_legacy_scope=lambda *_: None)
    native = SimpleNamespace(verify_binding=lambda *_: {
        'nativeRealm': 'controlled-seed', 'sessionId': 'original-session', 'evidenceRef': 'seed-session'})
    path = tmp_path / 'journal.sqlite'
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    journal = OperationJournal(path, acp_turn_opt_in=True)
    seed = SeedVerifier()
    original = UnitRecords(journal, scope_authority=scope, native_evidence=native,
        verifier=seed, epoch_port=SimpleNamespace(current_epoch=lambda _: 1), acp_turn_opt_in=True)
    unit, _ = original.reserve_unit(seed.issue('prepare', 'prepare-input'), provider_ref=provider,
        node_ref=node, input_digest='prepare-input', private_root_facts=roots)
    ticket = original.begin_session(unit.unit_ref, seed.issue('start', 'start-input'), input_digest='start-input')
    original.record_session(ticket, expected_source_revision=2, state='confirmed', evidence='seed-session')
    params = {'prompt': [], 'sessionId': 'original-session'}
    acp_turns.reserve(original, unit.public_ref, 'historical-turn', params)
    receipt = acp_turns.finish(original, 'historical-turn', 'unknown')
    claim = store.claim_operation_step(request, 'prepare-operation-input', step)
    store.record_operation_step(request, 'prepare-operation-input', 'prepare', step.input_digest,
        claim.step.revision, 'concluded', {'unitRef': unit.public_ref})
    operation = store.read_operation(request)
    store.publish_operation(request, 'prepare-operation-input', operation.revision, ('prepare',), (), (),
        {'nodeRef': node, 'unitRef': unit.public_ref, 'action': 'prepare'})
    owner_current = [True]
    def validate_owner():
        if not owner_current[0]:
            raise RuntimeError('controlled original owner no longer held')
    reopened = OperationJournal.reopen_for_new_units(path, namespace='env', validate_owner=validate_owner,
                                                    acp_turn_opt_in=True)
    now = [10.0]
    authority = LocalUnitInvocationAuthority(store, permission, owner_id='current-owner', clock=lambda: now[0])
    issuer = InvocationIssuer(store, authority, state, clock=lambda: now[0])
    def no_native(*_args, **_kwargs):
        raise AssertionError('historical query must not consult a native owner')
    records = UnitRecords(reopened, scope_authority=SimpleNamespace(verify_scope=lambda *_: False),
        native_evidence=SimpleNamespace(verify_binding=no_native), verifier=issuer.verifier(),
        epoch_port=state, acp_turn_opt_in=True)
    state.attach_owner(records, SimpleNamespace(records=records))
    owner = object.__new__(LocalUnitOwner)
    owner.permission, owner.environment, owner.state = permission, environment, state
    owner.authority, owner.owner_id = authority, 'current-owner'
    owner.acp_turn_opt_in, owner._effect_write_guard_factory_pending = True, False
    owner.admission = SimpleNamespace(environment_namespace='env', store_port=store, check_open=lambda: None)
    owner._ports = SimpleNamespace(issuer=issuer, provider_view=SimpleNamespace(records=records),
                                   validate_for=lambda _: None)
    try:
        yield SimpleNamespace(owner=owner, records=records, unit=unit, receipt=receipt, store=store,
            issuer=issuer, state=state, permission=permission, original_run=original_run,
            original_request=request, access=access, now=now, owner_current=owner_current)
    finally:
        issuer.close()
        store.close()


def _historical_query(world, request_id='historical-query'):
    request = RequestKey('env', world.permission.principal_scope, request_id)
    token = world.owner.authorize_acp_turn_query(world.owner.authorization(), request, world.unit.public_ref,
        'historical-turn', expected_prompt_input_digest=world.receipt['inputDigest'])
    return request, token


def test_historical_query_uses_current_permission_and_pins_original_source(historical_query_world):
    from ordessa_infrastructure.encoding.immutable_json import safe_json
    world = historical_query_world
    before = world.store.read_operation(world.original_request).intent_json
    request, token = _historical_query(world)
    operation = world.store.read_operation(request)
    context = operation.intent.context_ref
    assert context['localUnitRun']['ownerId'] == world.owner.owner_id != world.original_run['ownerId']
    assert context['localUnitRun']['permissionId'] == world.permission.identity != world.original_run['permissionId']
    assert safe_json(context['acpQuerySource']) == safe_json(world.state._query_source_ref(
        world.store.read_operation(world.original_request)))
    assert world.store.read_operation(world.original_request).intent_json == before
    assert world.issuer.verified_consumption(token) is False


@pytest.mark.parametrize('change', ['expired', 'revoked', 'authorization', 'generation', 'owner'])
def test_historical_query_rejects_current_permission_or_owner_change_before_issue(
        historical_query_world, change):
    world = historical_query_world
    authorization = world.owner.authorization()
    if change == 'expired':
        world.now[0] = world.permission.expires_at + 1
    elif change == 'revoked':
        world.access.revoke()
    elif change == 'authorization':
        authorization = object()
    elif change == 'generation':
        world.owner.environment.snapshot.generation += 1
    else:
        world.owner_current[0] = False
    request = RequestKey('env', world.permission.principal_scope, 'refused-historical-query')
    with pytest.raises((InvocationAuthorityRefused, AccessError)):
        world.owner.authorize_acp_turn_query(authorization, request, world.unit.public_ref,
            'historical-turn', expected_prompt_input_digest=world.receipt['inputDigest'])
    assert world.store.read_operation(request) is None


@pytest.mark.parametrize('change', ['version', 'extra', 'request', 'digest', 'operation'])
def test_historical_query_issuer_refuses_swapped_or_open_source_descriptor(historical_query_world, change):
    import json
    from dataclasses import replace
    from ordessa_infrastructure.encoding.immutable_json import safe_json
    world = historical_query_world
    request, _token = _historical_query(world)
    original = world.store.read_operation(request)
    context = json.loads(safe_json(original.intent.context_ref))
    source = context['acpQuerySource']
    if change == 'version':
        source['contractVersion'] = 'unit-acp-query-source/2'
    elif change == 'extra':
        source['trust'] = True
    elif change == 'request':
        source['request']['requestId'] = 'another-original-preparation'
    elif change == 'digest':
        source['intentDigest'] = 'sha256:' + '0' * 64
    else:
        source['operationRef'] = 'another-operation'
    forged_request = RequestKey('env', world.permission.principal_scope, 'changed-query-' + change)
    forged = replace(original.intent, operation_ref='changed-query-' + change, context_ref=context)
    world.store.reserve_operation(forged_request, original.digest, forged)
    with pytest.raises(InvocationAuthorityRefused):
        world.issuer.issue_query(forged_request, original.digest, 'read')
    assert world.store.read_operation_step(forged_request, 'read') is None
