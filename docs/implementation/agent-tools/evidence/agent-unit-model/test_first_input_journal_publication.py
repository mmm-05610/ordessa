"""C vertical: actual Registry/Node/Issuer/input/journal/SQLite publication.

Native Unit, original Session receipt and input effect sources are controlled;
no production writer/process/model. Core and journal are separate real files.
"""
from dataclasses import replace
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[5] / 'products/agent-tools/tests/integration'))
sys.path.insert(0, str(Path(__file__).resolve().parents[5] / 'plugins/harness/tests'))
from test_node_publication import setup as node_fixture, source, Provider
from test_invocation_authority import Authority, CurrentState
from test_sessionless_input import Captures, reserve
from test_managed_input_reservations import Native
from test_native_unit_confirmation import UnitEvidence
from test_unit_records import parts as journal_parts, ROOT
from test_input_session_association import AssociationEvidence
from ordessa_environment_api import RequestKey, GuaranteeUnavailableError, UnknownResultError
from ordessa_environment_api.operations import OperationIntent, StepIntent, UsageMutation, operation_holder, node_holder, safe_json
from ordessa_persistence_sqlite import ProtectedFingerprintHmac
from ordessa_harness.application.operation_journal import OperationJournal
from ordessa_harness.application.unit_records import UnitRecords
from pacthold.agents.directory import DirectoryBindingRef
from pacthold.agents.nodes import NodePublicationEvidence
from pacthold.agents.invocation import InvocationIssuer
from pacthold.agents.inputs import (ManagedInputReservations, SessionlessNativeInputState, NativeInputState,
                                  FirstInputObservation, FIRST_SESSION_ATTEMPTS)


class JournalObservation:
    """Read actual original journal identity AND a distinct controlled effect."""
    def __init__(self, records, unit, issuer, association, capture, effect_identity):
        self.records, self.unit, self.issuer, self.association = records, unit, issuer, association
        self.capture, self.effect_identity = capture, effect_identity
        self.effect_known = True
        self.associate = True
        self.calls = 0

    def observe(self, operation, query):
        self.calls += 1
        binding = self.records.query_input_session(self.unit.unit_ref, query, input_digest=operation.digest)
        if binding.state == 'notCreated' and self.associate:
            binding = self.records.reconcile_input_session(self.unit.unit_ref, query, input_digest=operation.digest,
                         expected_source_revision=1, evidence=self.association.receipt)
        if binding.state != 'confirmed' or not self.effect_known:
            return None
        identity = binding.association_facts['identity']
        # Both facts refer to the frozen original input, not latest Session.
        assert safe_json(identity) == safe_json(self.effect_identity)
        captured = identity['capturedInputRef']
        actual = self.capture.values[captured['captureId']]
        assert actual.ref.to_dict() == dict(captured) and actual.node_ref == identity['nodeRef']
        provider = identity['providerRef']
        session_ref = source(provider, 'session:' + binding.native_facts['sessionId'])
        return FirstInputObservation(identity, binding.association_facts['associationRef'], session_ref,
                                     binding.source_revision, source(provider, 'separate-original-input-effect'))


@pytest.fixture
def vertical(node_fixture, tmp_path):
    _, store, env, _, owner, nodes, prepare_request, node, node_intent, _ = node_fixture
    provider = node_intent.steps[0].pinned_provider_ref
    directory = DirectoryBindingRef('env', 'directory', 1, 'sha256:' + 'd' * 64)
    authority, current = Authority(), CurrentState(provider, directory, node_intent.node_ref)
    issuer = InvocationIssuer(store, authority, current, clock=lambda: 50)
    jp = journal_parts(tmp_path)
    records = jp[0]
    records.verifier = issuer.verifier()
    unit_owner = UnitEvidence()
    records.native_unit_evidence = unit_owner
    flow = RequestKey('env', 'principal', 'original-unit-flow')
    bindings = {name: {'action': name, 'targetRef': node_intent.node_ref, 'delegationRef': None, 'cleanup': False}
                for name in ('prepare', 'start')}
    intent = OperationIntent('unit-flow', 'controlled-unit-flow', None,
        {'environmentNamespace': 'env', 'directoryBindingRef': directory.to_dict(), 'invocationBindings': bindings},
        (StepIntent('prepare', provider, 'unit-input', 'unit-prepare'), StepIntent('start', provider, 'start-input', 'unit-start')))
    store.reserve_operation(flow, 'flow-digest', intent)
    unit, _ = records.reserve_unit(issuer.issue(flow, 'flow-digest', 'prepare', 'prepare', node_intent.node_ref),
                                 provider_ref=provider, node_ref=node_intent.node_ref, input_digest='unit-input', private_root_facts=ROOT)
    store.record_operation_step(flow, 'flow-digest', 'prepare', 'unit-input', 1, 'concluded', {'unitRef': unit.public_ref})
    ticket = records.begin_unit(unit.unit_ref, issuer.issue(flow, 'flow-digest', 'start', 'start', node_intent.node_ref), input_digest='start-input')
    unit_source = unit_owner.reference(unit, 'receipt')
    records.record_unit(ticket, expected_source_revision=2, state='confirmed', evidence=unit_source)
    store.record_operation_step(flow, 'flow-digest', 'start', 'start-input', 1, 'concluded', {'evidenceRef': unit_source})
    nodes.reserve(prepare_request, 'digest', node_intent)
    step = node_intent.steps[0]
    receipt = source(provider, 'controlled-node-preparation')
    acquisition = UsageMutation('unit-resource', 0, None, operation_holder(prepare_request, node_intent.operation_ref), unit.public_ref, ('use',), 'active')
    store.claim_operation_step(prepare_request, 'digest', step, (acquisition,))
    store.record_operation_step(prepare_request, 'digest', step.step_id, step.input_digest, 1, 'concluded', {'evidenceRef': receipt})
    owner.evidence = NodePublicationEvidence(provider,
        {'nodeRef': node_intent.node_ref, 'harnessProviderRef': provider, 'harnessDefinitionRef': Provider.descriptor.definition_ref,
         'harnessUnitRef': unit.public_ref, 'profileSnapshotRef': node_intent.profile_snapshot_ref,
         'preparationContextRef': node_intent.context_ref, 'configurationTargetRef': unit.configuration_target_ref,
         'nativeSessionRefs': [], 'operationRef': node_intent.operation_ref},
        ({'stepId': step.step_id, 'providerRef': provider, 'inputDigest': step.input_digest,
          'recoveryCorrelation': step.recovery_correlation, 'evidenceRef': receipt},), (source(provider, 'controlled-access'),))
    transfer = replace(acquisition, expected_revision=1, expected_holder_ref=acquisition.holder_ref,
                       holder_ref=node_holder('env', 'node', 1))
    published = nodes.publish(prepare_request, 'digest', store.read_operation(prepare_request).revision, (transfer,))
    env._fingerprint_port = ProtectedFingerprintHmac({'fixture': b'controlled-input-hmac'}, active_key_id='fixture')
    state = SessionlessNativeInputState(published['nodeRef'], provider, unit.public_ref, unit_source,
                                      source(provider, 'session-absence'), 0, directory, source(provider, 'before-config'))
    captures, native = Captures(), Native(state)
    inputs = ManagedInputReservations(env, nodes, captures, native)
    p = store, env, node, captures, native, inputs, authority, current, issuer
    op = reserve(p)
    identity = ManagedInputReservations._first_identity(op)
    association = AssociationEvidence(unit, identity)
    records.input_association_evidence = association
    observation = JournalObservation(records, unit, issuer, association, captures, identity)
    inputs._first_observation = observation
    invocation = inputs.claim_dispatch(op.request, issuer)
    records.verifier.verify_and_consume(invocation, 'submitInput', provider, unit.public_ref, op.digest)
    store.record_operation_step(op.request, op.digest, 'native-input', op.digest, 1, 'unknown', {})
    return p, op, records, jp, unit, observation


def first_marker(p):
    return p[0].list_domain('env', FIRST_SESSION_ATTEMPTS)[0]


def cold_owner(vertical):
    p, op, records, jp, unit, observation = vertical
    observation.records = UnitRecords(OperationJournal(jp[1].path), scope_authority=jp[3], native_evidence=jp[4],
        verifier=p[8].verifier(), epoch_port=jp[5], native_unit_evidence=records.native_unit_evidence,
        input_association_evidence=records.input_association_evidence)
    return ManagedInputReservations(p[1], p[5]._nodes, None, None, observation)


def test_actual_original_journal_association_and_separate_effect_publish(vertical):
    p, op, records, jp, unit, observation = vertical
    result = p[5].reconcile_first_input(op.request, p[8])
    assert result.status == 'published' and first_marker(p)['value']['state'] == 'resolved'
    with jp[1]._connect() as db:
        row = db.execute('SELECT * FROM harness_unit_sessions').fetchone()
        assert row['state'] == 'confirmed' and row['source_revision'] == 2
    assert cold_owner(vertical).reconcile_first_input(op.request, p[8]) == result
    old = p[4].state
    p[4].state = NativeInputState(old.node_ref, old.provider_ref, old.unit_ref, result.result['sessionRef'],
                                result.result['sessionSourceRevision'], 0, old.directory_binding_ref, old.before_configuration_evidence)
    assert reserve(p, key='next-input', draft='next-draft').status == 'reserved'
    assert p[4].dispatch_calls == 0


@pytest.mark.parametrize('missing', ['effect', 'association'])
def test_one_known_fact_retains_core_unknown_and_allows_only_read_recovery(vertical, missing):
    p, op, records, jp, unit, observation = vertical
    if missing == 'effect': observation.effect_known = False
    else: observation.associate = False
    with pytest.raises(UnknownResultError): p[5].reconcile_first_input(op.request, p[8])
    assert p[0].read_operation(op.request).status == 'unknown' and first_marker(p)['value']['state'] == 'held'
    with jp[1]._connect() as db:
        assert db.execute('SELECT state FROM harness_unit_sessions').fetchone()[0] == ('confirmed' if missing == 'effect' else 'notCreated')
    with pytest.raises(UnknownResultError): reserve(p, key='blocked', draft='another')
    observation.effect_known, observation.associate = True, True
    assert cold_owner(vertical).reconcile_first_input(op.request, p[8]).status == 'published'
    assert p[4].dispatch_calls == 0


def test_core_commit_failure_keeps_real_journal_association_then_recovers(vertical, monkeypatch):
    p, op, records, jp, unit, observation = vertical
    original = p[0].record_operation_step
    monkeypatch.setattr(p[0], 'record_operation_step', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('core-record-crash')))
    with pytest.raises(RuntimeError): p[5].reconcile_first_input(op.request, p[8])
    with jp[1]._connect() as db:
        assert db.execute('SELECT state FROM harness_unit_sessions').fetchone()[0] == 'confirmed'
    assert p[0].read_operation_step(op.request, 'native-input').outcome == 'unknown'
    assert first_marker(p)['value']['state'] == 'held'
    monkeypatch.setattr(p[0], 'record_operation_step', original)
    assert cold_owner(vertical).reconcile_first_input(op.request, p[8]).status == 'published'
    assert p[4].dispatch_calls == 0


def test_owner_loss_after_journal_confirmation_cannot_publish_from_session_alone(vertical):
    p, op, records, jp, unit, observation = vertical
    observation.effect_known = False
    with pytest.raises(UnknownResultError): p[5].reconcile_first_input(op.request, p[8])
    observation.effect_known = True
    records.input_association_evidence.valid = False
    with pytest.raises(GuaranteeUnavailableError): cold_owner(vertical).reconcile_first_input(op.request, p[8])
    assert p[0].read_operation(op.request).status == 'unknown' and first_marker(p)['value']['state'] == 'held'
    assert p[4].dispatch_calls == 0
