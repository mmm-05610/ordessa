"""Original Local/Node/issuer/store owners; controlled permissions, no model."""
from dataclasses import replace
import pytest

from agent_tools_fixtures.manager_joint import build_joint_owner
from ordessa_infrastructure.identifiers import RequestKey
from ordessa_units.bindings.publication import decode_node_ref
from ordessa_units.bindings.dispatch_selection import UnitSelectionUnavailable
from ordessa_units.admission.invocation import InvocationAuthorityRefused
from ordessa_units.records import UnitRecords, OperationJournal
from ordessa_units.records.unit_records import UnitRecordsRefused
from ordessa_execution_api.environment import IdentityMismatchError, AdmissionRefusedError


@pytest.fixture
def owner(tmp_path):
    with build_joint_owner(tmp_path, acp_turn_opt_in=True) as j:
        operation = j.services.assembly.prepare(RequestKey('env', 'principal', 'prepare'), j.profile, {}, {})
        assert operation.status == 'published'
        node = decode_node_ref(operation.intent.node_ref)
        ref = j.services.nodes.read(node)['binding']['harnessUnitRef']
        j.current.acquired = dict(operation.intent.node_ref)
        j.current.evidence = dict(ref)
        j.original_operation, j.node, j.unit_ref = operation, node, ref
        yield j


def authorize(j, *, request='query', operation='turn', digest='sha256:' + 'a' * 64):
    return j.services.authorize_acp_turn_query(RequestKey('env', 'principal', request),
        j.unit_ref, operation, expected_prompt_input_digest=digest)


def guard(j, invocation, **changes):
    params = dict(expected_profile_revision=j.profile, query_invocation=invocation,
                  query_input_digest=invocation.facts['inputDigest'], require_live=False)
    params.update(changes)
    return j.services.guard_unit_selection(j.unit_ref, **params)


def test_original_query_recipe_and_read_cut(owner):
    j = owner; invocation = authorize(j)
    row = j.store.read_operation(RequestKey('env', 'principal', 'query'))
    assert row.intent.kind == 'unit-acp-query'
    assert j.store.read_operation_step(row.request, 'read') is None
    with guard(j, invocation) as receipt:
        assert receipt['permissionCut'] == 'authorized-read-time'
        assert receipt['currentThroughCommit'] is False
        assert receipt['liveDispatchAuthorized'] is False
        assert receipt['authorizedAt'] == 50
        assert receipt['authorityRevision'] == 'rev-1'
        assert receipt['managementEpoch'] == 0
        assert receipt['unitRef'] == j.unit_ref
        with pytest.raises(TypeError): receipt['currentThroughCommit'] = True
        # Revocation after the cut does not turn this receipt into a live guard.
        j.current.permitted = False
    with pytest.raises(InvocationAuthorityRefused):
        with guard(j, invocation): pass
    assert j.events.count('spawn') == 1


def test_live_commit_contract_explicitly_refuses_unsynchronized_authority(owner):
    j = owner; invocation = authorize(j)
    with pytest.raises(UnitSelectionUnavailable):
        with guard(j, invocation, require_live=True):
            raise AssertionError('weak read proof must not enter live COMMIT guard')
    assert j.store.read_operation_step(RequestKey('env', 'principal', 'query'), 'read') is None


@pytest.mark.parametrize('change', ['principal', 'source', 'digest', 'authority', 'policy'])
def test_refused_query_does_not_reserve_read_operation(owner, change):
    j = owner
    request = RequestKey('env', 'other' if change == 'principal' else 'principal', 'denied')
    ref = dict(j.unit_ref)
    digest = 'sha256:' + 'a' * 64
    if change == 'source': ref['sourceRevision'] = 'wrong'
    if change == 'digest': digest = 'not-a-prompt-digest'
    if change == 'authority': j.inputs.authority.allowed = False
    if change == 'policy': j.env._policy.allowed = False
    with pytest.raises((IdentityMismatchError, AdmissionRefusedError, InvocationAuthorityRefused)):
        j.services.authorize_acp_turn_query(request, ref, 'turn', expected_prompt_input_digest=digest)
    assert j.store.read_operation(request) is None


@pytest.mark.parametrize('change', ['profile', 'digest', 'copied', 'authority_revision', 'epoch', 'directory'])
def test_guard_exact_original_profile_permission_and_context(owner, change):
    import copy
    j = owner; invocation = authorize(j); changes = {}
    if change == 'profile': changes['expected_profile_revision'] = replace(j.profile, revision=j.profile.revision + 1)
    if change == 'digest': changes['query_input_digest'] = 'sha256:' + 'b' * 64
    if change == 'copied': invocation = copy.copy(invocation)
    if change == 'authority_revision': j.inputs.authority.revision = 'rev-2'
    if change == 'epoch': j.current.epoch = 1
    if change == 'directory': j.current.permitted = False
    with pytest.raises((IdentityMismatchError, InvocationAuthorityRefused)):
        with guard(j, invocation, **changes): pass


def test_historical_selection_after_stop_release_uses_records_not_manager(owner):
    j = owner
    j.services.lifecycle.stop(RequestKey('env', 'principal', 'stop'), j.node, {})
    j.services.lifecycle.release(RequestKey('env', 'principal', 'release'), j.node, {})
    assert j.manager.list() == () and j.local.instance.snapshot.active_uses == 0
    j.current.active = False
    invocation = authorize(j)
    with guard(j, invocation) as receipt:
        assert receipt['unitRef'] == j.unit_ref
        assert receipt['currentThroughCommit'] is False
    assert j.events.count('spawn') == 1


def test_read_request_cannot_be_rebound_to_another_acp_operation(owner):
    j = owner; authorize(j)
    with pytest.raises(IdentityMismatchError): authorize(j, operation='different-turn')
    assert j.store.read_operation(RequestKey('env', 'principal', 'query')).intent.context_ref['acpTurnRead']['operationRef'] == 'turn'


def test_original_recorded_turn_new_public_query_cold_digest_and_no_replay(owner):
    from types import SimpleNamespace
    j = owner; unit = j.manager.find(j.unit_ref)
    lease = unit.lease_port.grant(j.unit_ref)
    original = unit.prompt_recorded(j.unit_ref, lease, operation_ref='turn', timeout=2, prompt=[])
    assert original['state'] == 'completed'
    invocation = authorize(j, digest=original['inputDigest'])
    def no_native(*_): raise AssertionError('cold read cannot observe native handles')
    cold = UnitRecords(OperationJournal(j.records.journal.path), scope_authority=j.inputs.scope_authority,
        native_evidence=SimpleNamespace(verify_binding=no_native), verifier=j.view.verifier,
        epoch_port=j.inputs.management_epoch)
    queried = cold.query_acp_turn(j.unit_ref, 'turn', invocation,
        input_digest=invocation.facts['inputDigest'], expected_prompt_input_digest=original['inputDigest'])
    assert queried == original
    with pytest.raises(UnitRecordsRefused):
        cold.query_acp_turn(j.unit_ref, 'wrong-operation', invocation,
            input_digest=invocation.facts['inputDigest'], expected_prompt_input_digest=original['inputDigest'])
    with pytest.raises(UnitRecordsRefused):
        cold.query_acp_turn(j.unit_ref, 'turn', invocation,
            input_digest=original['inputDigest'], expected_prompt_input_digest=original['inputDigest'])
    with pytest.raises(UnitRecordsRefused, match='no replay'):
        unit.prompt_recorded(j.unit_ref, lease, operation_ref='turn', prompt=[])
    j.services.profiles.archive(profile_id='joint', expected_version=1,
        request=RequestKey('env', 'principal', 'archive'))
    with guard(j, invocation) as receipt:
        assert receipt['profileRevision']['contentDigest'] == j.profile.digest
    assert j.events.count('spawn') == 1
