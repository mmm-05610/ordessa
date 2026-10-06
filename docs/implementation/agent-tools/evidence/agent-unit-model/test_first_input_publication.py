"""C: original SQLite/Issuer publication; controlled original receipt owner.

No production input writer, process or model. Separate actual journal tests
exercise association; this owner tests the core publication/CAS boundaries.
"""
from dataclasses import replace
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[5] / 'products/agent-tools/tests/integration'))
from test_sessionless_input import first_input, node_fixture, reserve
from test_node_publication import source
from ordessa_environment_api import RequestKey, GuaranteeUnavailableError, IdentityMismatchError, UnknownResultError
from ordessa_environment_api.domain import DomainRevisionConflict
from ordessa_environment_api.operations import UsageMutation, OperationRevisionConflict, operation_holder, node_holder, safe_json
from pacthold.agents.inputs import (ManagedInputReservations, FirstInputObservation, NativeInputState,
                                  FIRST_SESSION_ATTEMPTS, FIRST_INPUT_RESULT_VERSION)
from pacthold.agents.invocation import InvocationAuthorityRefused


class Owner:
    """Explicit controlled original receipt owner, never native IO."""
    def __init__(self, issuer, operation):
        self.issuer = issuer
        identity = ManagedInputReservations._first_identity(operation)
        provider = identity['providerRef']
        self.reply = FirstInputObservation(identity, source(provider, 'original-association'),
            source(provider, 'original-session'), 2, source(provider, 'original-input-effect'),
            (UsageMutation('input-receipt-resource', 0, None, operation_holder(operation.request, operation.intent.operation_ref),
                           identity['unitRef'], ('use',), 'active', {'receipt': 'controlled-input'}),))
        self.calls = 0
        self.verify = True
        self.after = lambda: None

    def observe(self, operation, query):
        self.calls += 1
        if self.verify:
            self.issuer.verifier().verify_and_consume(query, 'query', operation.intent.steps[0].pinned_provider_ref,
                operation.intent.context_ref['sessionlessInputBinding']['unitRef'], operation.digest)
        self.after()
        return self.reply


@pytest.fixture
def publication(first_input):
    p = first_input
    operation = reserve(p)
    invocation = p[5].claim_dispatch(operation.request, p[8])
    p[8].verifier().verify_and_consume(invocation, 'submitInput', p[4].state.provider_ref, p[4].state.unit_ref, operation.digest)
    p[0].record_operation_step(operation.request, operation.digest, 'native-input', operation.digest, 1, 'unknown', {})
    owner = Owner(p[8], operation)
    inputs = ManagedInputReservations(p[1], p[5]._nodes, p[3], p[4], owner,
                                     invocation_issuer=p[8])
    return p, operation, owner, inputs


def marker(p):
    return p[0].list_domain('env', FIRST_SESSION_ATTEMPTS)[0]


def usages(p):
    return [dict(row) for row in p[0]._conn.execute('SELECT * FROM env_usages ORDER BY usage_id')]


def later_session(p, owner):
    old = p[4].state
    p[4].state = NativeInputState(old.node_ref, old.provider_ref, old.unit_ref,
        owner.reply.session_ref, owner.reply.session_source_revision, old.management_epoch,
        old.directory_binding_ref, old.before_configuration_evidence)


def test_dual_original_facts_publish_atomic_marker_and_usage(publication):
    p, op, owner, inputs = publication
    result = inputs.reconcile_first_input(op.request, p[8])
    assert result.status == 'published' and result.result['contractVersion'] == FIRST_INPUT_RESULT_VERSION
    assert result.result['effectEvidenceRef'] == dict(owner.reply.effect_evidence_ref)
    assert marker(p)['revision'] == 2 and marker(p)['value']['state'] == 'resolved'
    assert marker(p)['value']['publicationResult'] == result.result
    resource = next(u for u in usages(p) if u['usage_id'] == 'input-receipt-resource')
    assert resource['revision'] == 2 and resource['state'] == 'active'
    assert json.loads(resource['holder_ref']) == dict(node_holder('env', 'node', 1))
    assert p[4].dispatch_calls == 0
    assert p[0].read_operation_step(op.request, 'native-input').outcome == 'concluded'


def test_published_replay_uses_original_cas_and_transfers(publication):
    p, op, owner, inputs = publication
    published = inputs.reconcile_first_input(op.request, p[8])
    before_marker, before_usages = marker(p), usages(p)
    assert inputs.reconcile_first_input(op.request, p[8]) == published
    assert marker(p) == before_marker and usages(p) == before_usages
    assert owner.calls == 2 and p[4].dispatch_calls == 0


def test_concluded_crash_retains_hold_and_cold_read_publishes_without_claim(publication, monkeypatch):
    p, op, owner, inputs = publication
    publish = p[0].publish_operation
    def crash(*args, **kwargs): raise RuntimeError('controlled-publication-crash')
    monkeypatch.setattr(p[0], 'publish_operation', crash)
    with pytest.raises(RuntimeError): inputs.reconcile_first_input(op.request, p[8])
    step = p[0].read_operation_step(op.request, 'native-input')
    assert step.outcome == 'concluded' and marker(p)['value']['state'] == 'held'
    with pytest.raises(UnknownResultError): reserve(p, key='later', draft='later')
    monkeypatch.setattr(p[0], 'publish_operation', publish)
    cold = ManagedInputReservations(p[1], p[5]._nodes, None, None, owner,
                                    invocation_issuer=p[8])
    assert cold.reconcile_first_input(op.request, p[8]).status == 'published'
    assert p[0].read_operation_step(op.request, 'native-input') == step
    assert p[4].dispatch_calls == 0


@pytest.mark.parametrize('damage', ['missing', 'unverified', 'same-evidence', 'wrong-request', 'capture', 'correlation',
                                    'provider-bool', 'source-bool', 'revision-bool', 'released', 'wrong-holder', 'duplicate'])
def test_missing_or_wrong_dual_facts_do_not_conclude_or_release(publication, damage):
    p, op, owner, inputs = publication
    reply = owner.reply
    if damage == 'missing': owner.reply = None
    elif damage == 'unverified': owner.verify = False
    elif damage == 'same-evidence': owner.reply = replace(reply, effect_evidence_ref=reply.association_ref)
    elif damage in {'wrong-request', 'capture', 'correlation', 'provider-bool'}:
        identity = json.loads(safe_json(reply.identity))
        if damage == 'wrong-request': identity['request']['requestId'] = 'another'
        elif damage == 'capture': identity['capturedInputRef']['captureRevision'] = True
        elif damage == 'correlation': identity['nativeCorrelation']['requestId'] = 'another'
        else: identity['providerRef']['generation'] = True
        owner.reply = replace(reply, identity=identity)
    elif damage == 'source-bool':
        ref = json.loads(safe_json(reply.effect_evidence_ref)); ref['ownerProviderRef']['generation'] = True
        owner.reply = replace(reply, effect_evidence_ref=ref)
    elif damage == 'revision-bool':
        with pytest.raises(ValueError): replace(reply, session_source_revision=True)
        return
    else:
        usage = reply.usages[0]
        if damage == 'released': owner.reply = replace(reply, usages=(replace(usage, state='released'),))
        elif damage == 'wrong-holder': owner.reply = replace(reply, usages=(replace(usage, holder_ref=node_holder('env', 'node', 1)),))
        else: owner.reply = replace(reply, usages=reply.usages * 2)
    before = p[0].read_operation_step(op.request, 'native-input')
    with pytest.raises((GuaranteeUnavailableError, IdentityMismatchError, UnknownResultError)):
        inputs.reconcile_first_input(op.request, p[8])
    assert p[0].read_operation_step(op.request, 'native-input') == before
    assert marker(p)['value']['state'] == 'held' and len(usages(p)) == 1
    assert p[4].dispatch_calls == 0


@pytest.mark.parametrize('resource', ['owner', 'issuer', 'different-store'])
def test_missing_explicit_ports_refuse_without_observing(publication, resource, tmp_path):
    p, op, owner, inputs = publication
    issuer = p[8]
    other = None
    if resource == 'owner': inputs._first_observation = None
    elif resource == 'issuer': issuer = None
    else:
        from ordessa_persistence_sqlite import SqliteStorePort
        from pacthold.agents.invocation import InvocationIssuer
        other = SqliteStorePort(tmp_path / 'different.sqlite')
        issuer = InvocationIssuer(other, p[6], p[7], clock=lambda: 50)
    try:
        with pytest.raises(GuaranteeUnavailableError): inputs.reconcile_first_input(op.request, issuer)
        assert owner.calls == 0 and marker(p)['value']['state'] == 'held'
    finally:
        if other is not None: other.close()


@pytest.mark.parametrize('revoke', ['authority', 'activation', 'directory', 'epoch', 'expiry'])
def test_owner_observation_revocation_retains_original_unknown(publication, revoke):
    p, op, owner, inputs = publication
    def change():
        if revoke == 'authority': p[6].allowed = False
        elif revoke == 'activation': p[7].active = False
        elif revoke == 'directory': p[7].permitted = False
        elif revoke == 'epoch': p[7].epoch = 1
        else: p[6].expiry = 49
    owner.after = change
    with pytest.raises(InvocationAuthorityRefused): inputs.reconcile_first_input(op.request, p[8])
    assert p[0].read_operation_step(op.request, 'native-input').outcome == 'unknown'
    assert marker(p)['value']['state'] == 'held' and len(usages(p)) == 1


def test_only_matching_published_session_allows_next_input(publication):
    p, op, owner, inputs = publication
    inputs.reconcile_first_input(op.request, p[8])
    later_session(p, owner)
    second = reserve(p, key='second', draft='second')
    assert 'sessionlessInputBinding' not in second.intent.context_ref
    assert second.intent.context_ref['nativeSessionRef'] == dict(owner.reply.session_ref)
    context = p[5].claim_dispatch(second.request, p[8])
    p[8].verifier().verify_and_consume(context, 'submitInput', p[4].state.provider_ref, p[4].state.session_ref, second.digest)
    assert p[4].dispatch_calls == 0


@pytest.mark.parametrize('change', ['session', 'revision', 'sessionless'])
def test_published_first_input_cannot_be_reopened_or_used_for_another_session(publication, change):
    p, op, owner, inputs = publication
    inputs.reconcile_first_input(op.request, p[8])
    if change != 'sessionless':
        later_session(p, owner)
        p[4].state = replace(p[4].state, **({'session_ref': source(p[4].state.provider_ref, 'another-session')}
                                         if change == 'session' else {'source_revision': 3}))
    with pytest.raises(GuaranteeUnavailableError): reserve(p, key='second', draft='second')
    assert p[0].read_operation(RequestKey('env', 'principal', 'second')) is None


def test_forged_resolved_marker_is_not_publication(publication):
    p, op, owner, inputs = publication
    m = marker(p)
    value = dict(m['value'], state='resolved', publicationResult={'nodeRef': m['value']['nodeRef']})
    p[0]._conn.execute('UPDATE env_domain_records SET revision=2,payload=? WHERE namespace=?',
                       (safe_json(value), FIRST_SESSION_ATTEMPTS))
    later_session(p, owner)
    with pytest.raises(GuaranteeUnavailableError): reserve(p, key='second', draft='second')
    assert p[0].read_operation(op.request).status == 'unknown'


@pytest.mark.parametrize('failure', ['domain-cas', 'usage-cas', 'missing-usage'])
def test_publication_conflict_rolls_back_marker_result_and_usage(publication, monkeypatch, failure):
    p, op, owner, inputs = publication
    original = p[0].publish_operation
    def conflict(request, digest, revision, required, writes, transfers, result):
        if failure == 'domain-cas': writes = (replace(writes[0], expected_revision=0),)
        elif failure == 'usage-cas': transfers = (replace(transfers[0], expected_revision=0),)
        else: transfers = ()
        return original(request, digest, revision, required, writes, transfers, result)
    monkeypatch.setattr(p[0], 'publish_operation', conflict)
    with pytest.raises((DomainRevisionConflict, OperationRevisionConflict, IdentityMismatchError)):
        inputs.reconcile_first_input(op.request, p[8])
    assert p[0].read_operation_step(op.request, 'native-input').outcome == 'concluded'
    assert p[0].read_operation(op.request).status == 'running' and p[0].read_operation(op.request).result is None
    assert marker(p)['revision'] == 1 and marker(p)['value']['state'] == 'held'
    held = next(u for u in usages(p) if u['usage_id'] == 'input-receipt-resource')
    assert held['revision'] == 1 and json.loads(held['holder_ref'])['kind'] == 'operation'
    monkeypatch.setattr(p[0], 'publish_operation', original)
    assert inputs.reconcile_first_input(op.request, p[8]).status == 'published'


def test_concluded_or_published_recovery_cannot_refresh_original_receipt(publication, monkeypatch):
    p, op, owner, inputs = publication
    original = p[0].publish_operation
    monkeypatch.setattr(p[0], 'publish_operation', lambda *a: (_ for _ in ()).throw(RuntimeError('crash')))
    with pytest.raises(RuntimeError): inputs.reconcile_first_input(op.request, p[8])
    before = p[0].read_operation_step(op.request, 'native-input')
    monkeypatch.setattr(p[0], 'publish_operation', original)
    reply = owner.reply
    owner.reply = replace(reply, effect_evidence_ref=source(reply.identity['providerRef'], 'different-receipt'))
    with pytest.raises(IdentityMismatchError): inputs.reconcile_first_input(op.request, p[8])
    assert p[0].read_operation_step(op.request, 'native-input') == before and marker(p)['value']['state'] == 'held'
    owner.reply = reply
    published = inputs.reconcile_first_input(op.request, p[8])
    owner.reply = replace(reply, usages=())
    with pytest.raises(IdentityMismatchError): inputs.reconcile_first_input(op.request, p[8])
    assert p[0].read_operation(op.request) == published


@pytest.mark.parametrize('window', ['owner', 'concluded'])
def test_core_policy_revocation_rechecked_before_conclusion_and_publication(publication, monkeypatch, window):
    from ordessa_environment_api import AdmissionRefusedError
    p, op, owner, inputs = publication
    policy = p[1]._policy
    if window == 'owner': owner.after = lambda: setattr(policy, 'allowed', False)
    else:
        original = p[0].record_operation_step
        def record(*args, **kwargs):
            result = original(*args, **kwargs)
            policy.allowed = False
            return result
        monkeypatch.setattr(p[0], 'record_operation_step', record)
    with pytest.raises(AdmissionRefusedError): inputs.reconcile_first_input(op.request, p[8])
    assert marker(p)['value']['state'] == 'held' and p[0].read_operation(op.request).result is None
    assert p[0].read_operation_step(op.request, 'native-input').outcome == ('unknown' if window == 'owner' else 'concluded')


def test_unknown_usage_requires_original_conclusion_before_atomic_transfer(publication):
    p, op, owner, inputs = publication
    step = p[0].read_operation_step(op.request, 'native-input')
    original = owner.reply.usages[0]
    p[0].record_operation_step(op.request, op.digest, 'native-input', op.digest, step.revision, 'unknown',
                              {'evidenceRef': source(original.target_ref['ownerProviderRef'], 'unknown-receipt')},
                              usages=(replace(original, state='unknown'),))
    owner.reply = replace(owner.reply, usages=(replace(original, expected_revision=1, expected_holder_ref=original.holder_ref),))
    published = inputs.reconcile_first_input(op.request, p[8])
    held = next(u for u in usages(p) if u['usage_id'] == original.usage_id)
    assert published.status == 'published' and held['revision'] == 3 and held['state'] == 'active'
    assert json.loads(held['holder_ref'])['kind'] == 'node'
    before = usages(p)
    assert inputs.reconcile_first_input(op.request, p[8]) == published and usages(p) == before


def test_unaccounted_unknown_usage_prevents_publication_without_releasing_any_hold(publication):
    p, op, owner, inputs = publication
    extra = UsageMutation('unaccounted-native-resource', 0, None, operation_holder(op.request, op.intent.operation_ref),
                          owner.reply.identity['unitRef'], ('use',), 'unknown')
    step = p[0].read_operation_step(op.request, 'native-input')
    p[0].record_operation_step(op.request, op.digest, 'native-input', op.digest, step.revision, 'unknown',
                              {'evidenceRef': source(owner.reply.identity['providerRef'], 'unknown-extra')}, usages=(extra,))
    with pytest.raises(IdentityMismatchError): inputs.reconcile_first_input(op.request, p[8])
    assert marker(p)['value']['state'] == 'held' and p[0].read_operation(op.request).result is None
    assert all(json.loads(u['holder_ref'])['kind'] == 'operation' for u in usages(p) if u['usage_id'] != 'resource')
    assert next(u for u in usages(p) if u['usage_id'] == extra.usage_id)['state'] == 'unknown'


def test_missing_usage_reply_can_be_completed_by_original_read_only_recovery(publication):
    p, op, owner, inputs = publication
    extra = UsageMutation('recoverable-extra', 0, None, operation_holder(op.request, op.intent.operation_ref),
                          owner.reply.identity['unitRef'], ('use',), 'unknown')
    step = p[0].read_operation_step(op.request, 'native-input')
    p[0].record_operation_step(op.request, op.digest, 'native-input', op.digest, step.revision, 'unknown',
                              {'evidenceRef': source(owner.reply.identity['providerRef'], 'unknown-extra')}, usages=(extra,))
    before = p[0].read_operation_step(op.request, 'native-input')
    before_usages = usages(p)
    with pytest.raises(IdentityMismatchError): inputs.reconcile_first_input(op.request, p[8])
    assert p[0].read_operation_step(op.request, 'native-input') == before and usages(p) == before_usages
    original_extra = replace(extra, expected_revision=1, expected_holder_ref=extra.holder_ref, state='active')
    owner.reply = replace(owner.reply, usages=owner.reply.usages + (original_extra,))
    assert inputs.reconcile_first_input(op.request, p[8]).status == 'published'
    assert all(json.loads(u['holder_ref'])['kind'] == 'node' and u['state'] == 'active' for u in usages(p))
    assert p[4].dispatch_calls == 0


def test_published_operation_with_held_marker_is_damage_not_recoverable_publication(publication):
    p, op, owner, inputs = publication
    inputs.reconcile_first_input(op.request, p[8])
    m = marker(p)
    value = {key: value for key, value in m['value'].items() if key != 'publicationResult'}
    value['state'] = 'held'
    p[0]._conn.execute('UPDATE env_domain_records SET revision=1,payload=? WHERE namespace=?',
                       (safe_json(value), FIRST_SESSION_ATTEMPTS))
    with pytest.raises(GuaranteeUnavailableError): inputs.reconcile_first_input(op.request, p[8])
    assert marker(p)['value']['state'] == 'held'


def test_late_owner_reply_cannot_refresh_step_revision_or_downgrade_conclusion(publication):
    p, op, owner, inputs = publication
    def late():
        previous = p[0].read_operation_step(op.request, 'native-input')
        p[0].record_operation_step(op.request, op.digest, 'native-input', op.digest, previous.revision, 'unknown',
                                  {'evidenceRef': source(owner.reply.identity['providerRef'], 'other-original-observation')})
    owner.after = late
    with pytest.raises(OperationRevisionConflict): inputs.reconcile_first_input(op.request, p[8])
    step = p[0].read_operation_step(op.request, 'native-input')
    assert step.revision == 3 and step.outcome == 'unknown' and first_marker_state(p) == 'held'
    owner.after = lambda: None
    published = inputs.reconcile_first_input(op.request, p[8])
    with pytest.raises(OperationRevisionConflict):
        p[0].record_operation_step(op.request, op.digest, 'native-input', op.digest, step.revision, 'unknown', {})
    assert p[0].read_operation(op.request) == published and p[4].dispatch_calls == 0


def first_marker_state(p):
    return marker(p)['value']['state']


def test_session_request_cannot_be_reinterpreted_as_first_input(publication):
    p, op, owner, inputs = publication
    inputs.reconcile_first_input(op.request, p[8])
    later_session(p, owner)
    session_op = reserve(p, key='session-request', draft='session-draft')
    with pytest.raises(GuaranteeUnavailableError): inputs.reconcile_first_input(session_op.request, p[8])
    assert p[0].read_operation_step(session_op.request, 'native-input') is None


def test_ack_shape_is_not_known_dual_fact(publication):
    p, op, owner, inputs = publication
    owner.reply = {'accepted': True}
    with pytest.raises(UnknownResultError): inputs.reconcile_first_input(op.request, p[8])
    assert p[0].read_operation_step(op.request, 'native-input').outcome == 'unknown'
    assert first_marker_state(p) == 'held'


@pytest.mark.parametrize('flag', [True, 1])
def test_complete_usage_check_cannot_be_attached_to_unknown_step(publication, flag):
    p, op, owner, inputs = publication
    before = p[0].read_operation_step(op.request, 'native-input')
    with pytest.raises(ValueError):
        p[0].record_operation_step(op.request, op.digest, 'native-input', op.digest, before.revision, 'unknown', {},
                                  require_complete_usages=flag)
    assert p[0].read_operation_step(op.request, 'native-input') == before


def test_existing_active_usage_omission_keeps_step_and_can_recover(publication):
    p, op, owner, inputs = publication
    extra = UsageMutation('active-extra', 0, None, operation_holder(op.request, op.intent.operation_ref),
                          owner.reply.identity['unitRef'], ('use',), 'active')
    step = p[0].read_operation_step(op.request, 'native-input')
    p[0].record_operation_step(op.request, op.digest, 'native-input', op.digest, step.revision, 'unknown',
                              {'evidenceRef': source(owner.reply.identity['providerRef'], 'active-held-extra')}, usages=(extra,))
    before_step, before_usages = p[0].read_operation_step(op.request, 'native-input'), usages(p)
    with pytest.raises(IdentityMismatchError): inputs.reconcile_first_input(op.request, p[8])
    assert p[0].read_operation_step(op.request, 'native-input') == before_step and usages(p) == before_usages
    owner.reply = replace(owner.reply, usages=owner.reply.usages + (
        replace(extra, expected_revision=1, expected_holder_ref=extra.holder_ref),))
    assert inputs.reconcile_first_input(op.request, p[8]).status == 'published'
    assert all(json.loads(u['holder_ref'])['kind'] == 'node' for u in usages(p))


def test_complete_usage_conclusion_replay_preserves_original_cas_and_flag_identity(publication):
    p, op, owner, inputs = publication
    previous = p[0].read_operation_step(op.request, 'native-input')
    evidence = inputs._observation_evidence(op, owner.reply)
    recorded = p[0].record_operation_step(op.request, op.digest, 'native-input', op.digest, previous.revision,
                'concluded', evidence, usages=owner.reply.usages, require_complete_usages=True)
    before = usages(p)
    assert p[0].record_operation_step(op.request, op.digest, 'native-input', op.digest, previous.revision,
                'concluded', evidence, usages=owner.reply.usages, require_complete_usages=True) == recorded
    assert usages(p) == before
    with pytest.raises(OperationRevisionConflict):
        p[0].record_operation_step(op.request, op.digest, 'native-input', op.digest, previous.revision,
                'concluded', evidence, usages=owner.reply.usages, require_complete_usages=False)
    assert p[0].read_operation_step(op.request, 'native-input') == recorded and usages(p) == before
    assert inputs.reconcile_first_input(op.request, p[8]).status == 'published'
