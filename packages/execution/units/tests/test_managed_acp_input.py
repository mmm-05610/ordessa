"""Original SQLite/Local Unit owners; controlled ACP peer, no model or secrets."""
from dataclasses import replace
import hashlib
import json

import pytest

from test_local_owner import live_owner
from ordessa_infrastructure.encoding.immutable_json import safe_json
from ordessa_infrastructure.identifiers import RequestKey
from ordessa_units.api import ManagedAcpCapture, ManagedAcpInputPorts, UnitApiRefused
from ordessa_units.errors import UnitIdentityMismatch
from ordessa_units.channels.acp_input import operation_reference
from ordessa_units.channels.contracts import WorkspaceExecutionEvidence
from ordessa_units.channels.reservations import CapturedInputRef
from ordessa_units.admission.invocation import InvocationAuthorityRefused
from ordessa_units.admission.connection import ConnectionLeaseRefused
from ordessa_agents.profiles import encode_revision_ref
from ordessa_units.records import UnitRecordsRefused


class Captures:
    def __init__(self):
        self.content, self.reads = None, 0

    def read_content(self, ref, principal):
        self.reads += 1
        return self.content


class Workspace:
    def __init__(self):
        self.authorizations, self.revalidations = 0, 0
        self.revoked = False
        self.transform = lambda proof: proof

    def authorize_execute(self, request, node_ref, unit_ref, operation_ref, capture_ref, digest, epoch):
        self.authorizations += 1
        return self.transform(WorkspaceExecutionEvidence(request.environment_namespace,
            request.principal_scope, node_ref, unit_ref, operation_ref, capture_ref, digest, epoch,
            'controlled-workspace-execute'))

    def revalidate_execute(self, proof):
        self.revalidations += 1
        return None if self.revoked else proof


CAPTURES, WORKSPACE = Captures(), Workspace()
PORTS = ManagedAcpInputPorts(CAPTURES, WORKSPACE)


@pytest.fixture
def managed(request):
    # Indirect fixture selection uses explicit constructor ports, never swaps
    # a live production owner or invents a replacement issuer/verifier.
    CAPTURES.__init__()
    WORKSPACE.__init__()
    return PORTS


def capture(world, unit, text='captured original text'):
    node = world.records.owner_read_unit(unit.identity['unitId']).facts['nodeRef']
    provisional = ManagedAcpCapture(CapturedInputRef('env', 'capture', 1, 'sha256:' + 'a' * 64),
        node, unit.identity, {'prompt': [{'type': 'text', 'text': text}]})
    ref = replace(provisional.ref, content_digest='sha256:' + hashlib.sha256(provisional.canonical_bytes()).hexdigest())
    CAPTURES.content = replace(provisional, ref=ref)
    return ref


def setup(world):
    authorization = world.owner.authorization()
    unit = world.public_manager.create(world.owner.spec, authorization)
    ref = capture(world, unit)
    request = RequestKey('env', world.permission.principal_scope, 'original-input')
    return authorization, unit, ref, request


OPTIONS = {'acp_turn_opt_in': True, 'managed_input_ports': PORTS}
pytestmark = pytest.mark.parametrize('live_owner', [OPTIONS], indirect=True)


def test_submit_same_attempt_replays_original_receipt_and_cold_read_without_refresh(live_owner, managed):
    world = live_owner
    authorization, unit, ref, request = setup(world)
    interaction = unit.interaction(authorization)
    first = interaction.submit_input(request, ref, timeout=3)
    assert first['contractVersion'] == 'unit-acp-turn/2'
    assert first['state'] == 'completed'
    assert first['operationRef'] == operation_reference(request)
    assert first['managedInput']['capturedInputRef'] == ref.to_dict()
    assert first['managedInput']['issuerRef'] == world.owner.authority.issuer_ref
    assert first['managedInput']['profileRevision'] == encode_revision_ref(world.profile.current_revision)
    assert first['response']['result']['observedPrompt'] == CAPTURES.content.params['prompt']
    assert 'managedInput' not in first['request']['raw']['params']
    assert WORKSPACE.authorizations == 1 and WORKSPACE.revalidations == 1
    reads = CAPTURES.reads
    CAPTURES.content = None
    WORKSPACE.revoked = True
    replay = interaction.submit_input(request, ref, timeout=3)
    assert replay == first and CAPTURES.reads == reads and WORKSPACE.authorizations == 1
    interaction.disconnect()
    assert unit.close(authorization)['state'] == 'confirmed'
    assert world.public_manager.read_input(authorization, request, unit.identity, ref) == first
    assert world.public_manager.list() == ()
    assert CAPTURES.reads == reads and WORKSPACE.authorizations == 1
    with world.records.journal._connect() as db:
        assert db.execute('SELECT count(*) FROM harness_acp_turn_attempts').fetchone()[0] == 1
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='harness_managed_turn_attempts'").fetchone()
    assert world.store.read_operation(request) is None  # no second managed-input ledger


def test_spent_request_conflicting_capture_or_principal_refused(live_owner, managed):
    world = live_owner
    authorization, unit, ref, request = setup(world)
    first = world.owner.submit_managed_input(unit, authorization, request, ref, timeout=3)
    changed = replace(ref, capture_revision=2)
    with pytest.raises(UnitIdentityMismatch):
        world.owner.submit_managed_input(unit, authorization, request, changed, timeout=3)
    foreign = RequestKey('env', 'other-principal', 'original-input')
    with pytest.raises(UnitIdentityMismatch):
        world.owner.submit_managed_input(unit, authorization, foreign, ref, timeout=3)
    with pytest.raises(UnitIdentityMismatch):
        world.owner.read_managed_input(authorization, request, dict(unit.identity, sourceRevision='forged'), ref)
    assert world.owner.read_managed_input(authorization, request, unit.identity, ref) == first


@pytest.mark.parametrize('field', ['principal_scope', 'operation_ref', 'content_digest', 'management_epoch', 'unit_ref'])
def test_mismatched_workspace_evidence_never_reserves_or_writes(live_owner, managed, field):
    world = live_owner
    authorization, unit, ref, request = setup(world)
    replacements = {'principal_scope': 'foreign', 'operation_ref': 'foreign',
        'content_digest': 'sha256:' + 'f' * 64, 'management_epoch': 999,
        'unit_ref': dict(unit.identity, sourceRevision='foreign')}
    WORKSPACE.transform = lambda proof: replace(proof, **{field: replacements[field]})
    with pytest.raises(UnitRecordsRefused):
        world.owner.submit_managed_input(unit, authorization, request, ref, timeout=3)
    with world.records.journal._connect() as db:
        assert db.execute('SELECT count(*) FROM harness_acp_turn_attempts').fetchone()[0] == 0


def test_workspace_revocation_at_write_edge_leaves_unknown_without_native_request_or_retry(live_owner, managed):
    world = live_owner
    authorization, unit, ref, request = setup(world)
    WORKSPACE.revoked = True
    with pytest.raises(Exception):
        world.owner.submit_managed_input(unit, authorization, request, ref, timeout=3)
    receipt = world.owner.read_managed_input(authorization, request, unit.identity, ref)
    assert receipt['state'] == 'unknown' and receipt['request'] is None
    assert not receipt['summary']['successfulRpcResponse']
    reads = CAPTURES.reads
    assert world.owner.submit_managed_input(unit, authorization, request, ref, timeout=3) == receipt
    assert CAPTURES.reads == reads and WORKSPACE.revalidations == 1
    new_request = RequestKey('env', request.principal_scope, 'different-key')
    with pytest.raises((UnitRecordsRefused, ConnectionLeaseRefused)):
        world.owner.submit_managed_input(unit, authorization, new_request, ref, timeout=3)


def test_capture_changed_before_actual_write_is_unknown(live_owner, managed):
    world = live_owner
    authorization, unit, ref, request = setup(world)
    previous = CAPTURES.content
    def changed(proof):
        CAPTURES.content = replace(previous, params={'prompt': [{'type': 'text', 'text': 'changed'}]})
        return proof
    WORKSPACE.transform = changed
    with pytest.raises(Exception):
        world.owner.submit_managed_input(unit, authorization, request, ref, timeout=3)
    receipt = world.owner.read_managed_input(authorization, request, unit.identity, ref)
    assert receipt['state'] == 'unknown' and receipt['request'] is None


def test_expired_original_permission_cannot_replay_receipt(live_owner, managed):
    world = live_owner
    authorization, unit, ref, request = setup(world)
    world.owner.submit_managed_input(unit, authorization, request, ref, timeout=3)
    world.now[0] = world.permission.expires_at + 1
    with pytest.raises(InvocationAuthorityRefused):
        world.public_manager.read_input(authorization, request, unit.identity, ref)


def test_public_receipt_read_is_exact_and_does_not_create_missing_attempt(live_owner, managed):
    world = live_owner
    authorization, unit, ref, request = setup(world)
    assert world.public_manager.read_input(authorization, request, unit.identity, ref) is None
    assert CAPTURES.reads == 0 and WORKSPACE.authorizations == 0
    first = unit.interaction(authorization).submit_input(request, ref, timeout=3)
    reads = CAPTURES.reads
    with pytest.raises(UnitIdentityMismatch):
        world.public_manager.read_input(authorization, request, unit.identity,
            replace(ref, capture_revision=2))
    with pytest.raises(UnitIdentityMismatch):
        world.public_manager.read_input(authorization, request,
            dict(unit.identity, sourceRevision='foreign'), ref)
    foreign = RequestKey('env', 'other-principal', request.request_id)
    with pytest.raises(UnitIdentityMismatch):
        world.public_manager.read_input(authorization, foreign, unit.identity, ref)
    assert world.public_manager.read_input(authorization, request, unit.identity, ref) == first
    assert CAPTURES.reads == reads and WORKSPACE.authorizations == 1


def test_rehashed_managed_evidence_damage_is_rejected_on_original_read(live_owner, managed):
    world = live_owner
    authorization, unit, ref, request = setup(world)
    world.owner.submit_managed_input(unit, authorization, request, ref, timeout=3)
    from ordessa_units.records.acp_turns import digest
    with world.records.journal._connect() as db:
        row = db.execute('SELECT body_json FROM harness_acp_turn_attempts').fetchone()
        body = json.loads(row['body_json'])
        body['managedInput']['workspaceExecutionEvidence']['principalScope'] = 'foreign'
        db.execute('UPDATE harness_acp_turn_attempts SET body_json=?,body_digest=?', (safe_json(body), digest(body)))
    with pytest.raises(UnitRecordsRefused):
        world.owner.read_managed_input(authorization, request, unit.identity, ref)


def test_managed_input_does_not_bypass_canonical_engineering_guard(live_owner, managed):
    world = live_owner
    authorization, unit, ref, request = setup(world)
    instance = world.original_manager.find(unit.identity)
    instance._effect_write_guard_factory = instance._fixed_effect_write_guard_factory = lambda *_args: None
    with pytest.raises(UnitApiRefused, match='original Engineering binding'):
        world.owner.submit_managed_input(unit, authorization, request, ref, timeout=3)


def test_new_key_cannot_resubmit_same_capture_and_raw_prompt_cannot_bypass_selected_owner(live_owner, managed):
    world = live_owner
    authorization, unit, ref, request = setup(world)
    interaction = unit.interaction(authorization)
    first = interaction.submit_input(request, ref, timeout=3)
    with pytest.raises(UnitRecordsRefused, match='capture already submitted'):
        interaction.submit_input(RequestKey('env', request.principal_scope, 'new-key'), ref, timeout=3)
    with pytest.raises(UnitApiRefused, match='managed-input capture'):
        interaction.prompt({'prompt': [{'type': 'text', 'text': 'bypass'}]})
    assert world.owner.read_managed_input(authorization, request, unit.identity, ref) == first


def test_replay_during_inflight_attempt_returns_original_pending_record_without_second_send(live_owner, managed, monkeypatch):
    import threading
    from ordessa_units.records import acp_turns
    world = live_owner
    authorization, unit, ref, request = setup(world)
    dispatched, release = threading.Event(), threading.Event()
    original = acp_turns.dispatch
    def pause(records, operation, raw):
        original(records, operation, raw)
        dispatched.set()
        assert release.wait(3)
    monkeypatch.setattr(acp_turns, 'dispatch', pause)
    results, errors = [], []
    def submit():
        try:
            results.append(world.owner.submit_managed_input(unit, authorization, request, ref, timeout=5))
        except Exception as error:
            errors.append(error)
    worker = threading.Thread(target=submit)
    worker.start()
    try:
        assert dispatched.wait(3)
        reads = CAPTURES.reads
        pending = world.owner.submit_managed_input(unit, authorization, request, ref, timeout=3)
        assert pending['state'] == 'possibly-written' and pending['response'] is None
        assert pending['operationRef'] == operation_reference(request)
        assert CAPTURES.reads == reads and WORKSPACE.authorizations == 1
    finally:
        release.set()
        worker.join(6)
    assert not worker.is_alive() and errors == []
    assert len(results) == 1 and results[0]['state'] == 'completed'
    assert results[0]['request'] == pending['request']
