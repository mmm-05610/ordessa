"""C only: actual Codex provider/Core/UnitRecords, controlled native client.

No Codex executable, SDK, model or production deployment is exercised. The
test owner below is explicitly scoped to this fixture's authenticated request;
it is not a production lookup granting reads using another caller's identity.
"""
from types import SimpleNamespace

import pytest

from test_assembly import (
    Authority, CurrentState, Policy, source, Environment, InstallationRecord,
    AgentContributionSet, DirectoryBindingRef, InvocationIssuer, ProfileCatalog,
    NodePublication, NodePublicationEvidence, AgentAssembly, PreparationContext,
    PreparationObservation, RequestKey, SqliteStorePort, ProtectedFingerprintHmac,
    UsageMutation, operation_holder, decode_node_ref, safe_json,
)
from ordessa_harness.application.operation_journal import OperationJournal
from ordessa_harness.application.unit_records import UnitRecords, CanonicalConfigurationScopeRef
from ordessa_harness_codex import CodexRuntimeProvider


class NativeClient:
    def __init__(self):
        self.calls = []
        self.fail = False
        self.observed_id = 'controlled-thread'
        self.after_initialize = lambda: None

    def initialize(self):
        self.calls.append('initialize')
        self.after_initialize()

    def create_thread(self, **params):
        self.calls.append('thread/start')
        if self.fail:
            raise TimeoutError('controlled receipt loss')
        return {'thread': {'id': 'controlled-thread'}}

    def command(self, method, **params):
        self.calls.append(method)
        assert method == 'thread/read'
        assert params == {'threadId': 'controlled-thread', 'includeTurns': False}
        return {'thread': {'id': self.observed_id}}


class FixtureOwner:
    """Explicit C owner; all authorized reads use the original core issuer."""
    def resolve(self, request, manifest, admitted, node, context, options):
        assert request == self.request
        return PreparationContext(self.directory,
            {'installationRef': {'environmentNamespace': 'env', 'installationId': 'controlled', 'sourceRevision': '1'}},
            {'nodeRef': node, 'privateRootFacts': self.roots})

    def issue_scope(self, provider, node, roots):
        assert safe_json(roots) == safe_json(self.roots)
        return CanonicalConfigurationScopeRef('env', 'controlled-physical-scope', '1')

    def verify_scope(self, scope, roots):
        return scope == self.issue_scope(None, None, roots)

    def current_epoch(self, target):
        return self.current.epoch

    def map_legacy_scope(self, target):
        raise AssertionError('no legacy fixture operations')

    def verify_preparation(self, plan, facts):
        op = self.store.read_operation(self.request)
        assert op is not None and facts['operationRef'] == op.intent.operation_ref
        assert plan['correlation']['prepareCorrelation'] == op.intent.steps[0].recovery_correlation
        assert safe_json(plan['context']['privateRootFacts']) == safe_json(self.roots)
        assert safe_json(plan['context']['nodeRef']) == safe_json(op.intent.node_ref)
        return self.roots

    def read_context(self, step='prepare'):
        op = self.store.read_operation(self.request)
        return self.issuer.issue_query(self.request, op.digest, step)

    def original_unit(self):
        # Enumerating this fixture owner's journal does not grant permission.
        with self.journal._connect() as db:
            rows = db.execute('SELECT unit_ref FROM harness_unit_reservations').fetchall()
        assert len(rows) == 1
        context = self.read_context()
        return self.records.read_unit(rows[0]['unit_ref'], context, input_digest=context.facts['inputDigest'])

    def read_unit(self, ref):
        context = self.read_context()
        return self.records.resolve_unit_reference(ref, context, input_digest=context.facts['inputDigest'])

    def read_session(self, ref):
        unit = self.read_unit(ref)
        context = self.read_context('start')
        return self.records.read_session(unit.unit_ref, context, input_digest=context.facts['inputDigest'])

    def revalidate_start(self, unit, context):
        return self.issuer.verify_continuation(context, 'start', unit.facts['providerRef'],
                                               unit.facts['nodeRef'], context.facts['inputDigest'])

    def publish_channel(self, unit, client, native):
        assert client is self.client and native == {'thread': {'id': 'controlled-thread'}}
        self.receipt = (unit.unit_ref, native['thread']['id'])
        return 'controlled-original-thread-evidence'

    def verify_binding(self, unit, correlation, evidence):
        assert evidence == 'controlled-original-thread-evidence'
        assert self.receipt == (unit.unit_ref, 'controlled-thread')
        op = self.store.read_operation(self.request)
        assert correlation == safe_json({'request': {
            'environmentNamespace': self.request.environment_namespace,
            'principalScope': self.request.principal_scope, 'requestId': self.request.request_id},
            'operationRef': op.intent.operation_ref, 'stepId': 'start'})
        return {'nativeRealm': 'controlled-codex', 'sessionId': self.receipt[1], 'evidenceRef': evidence}

    def publication_facts(self, ref):
        raise AssertionError('core publication must use original owner evidence')

    def query_creation(self, correlation, facts):
        op = self.store.read_operation(self.request)
        assert facts['query'] is True and facts['operationRef'] == op.intent.operation_ref
        step = next(item for item in op.intent.steps if item.step_id == facts['stepId'])
        assert correlation == step.recovery_correlation
        unit = self.original_unit()
        context = self.read_context(step.step_id)
        binding = self.records.read_session(unit.unit_ref, context, input_digest=context.facts['inputDigest'])
        return {'unitRef': unit.public_ref, 'state': binding.state}

    def observe(self, operation, step, reply):
        assert operation.request == self.request
        unit = self.original_unit()
        if step.step_id == 'start':
            assert self.read_session(unit.public_ref).state == 'confirmed'
        elif reply is not None:
            assert safe_json(reply['unitRef']) == safe_json(unit.public_ref)
        usages = () if step.step_id == 'start' else (
            UsageMutation(operation.intent.operation_ref + '.unit', 0, None,
                operation_holder(self.request, operation.intent.operation_ref), unit.public_ref, ('use',), 'active'),)
        return PreparationObservation(step.step_id, step.pinned_provider_ref, step.input_digest,
            step.recovery_correlation, source(step.pinned_provider_ref, step.step_id + '-journal'),
            {'unitRef': unit.public_ref}, usages)

    def inspect(self, operation, steps):
        unit = self.original_unit()
        binding = self.read_session(unit.public_ref)
        assert binding.state == 'confirmed'
        provider = unit.facts['providerRef']
        return NodePublicationEvidence(provider, {
            'nodeRef': operation.intent.node_ref, 'operationRef': operation.intent.operation_ref,
            'profileSnapshotRef': operation.intent.profile_snapshot_ref,
            'preparationContextRef': operation.intent.context_ref, 'harnessProviderRef': provider,
            'harnessDefinitionRef': self.provider.descriptor.definition_ref,
            'harnessUnitRef': unit.public_ref, 'configurationTargetRef': unit.configuration_target_ref,
            'nativeSessionRefs': [source(provider, binding.native_facts['sessionId'])]},
            tuple({'stepId': row.intent.step_id, 'providerRef': row.intent.pinned_provider_ref,
                   'inputDigest': row.intent.input_digest, 'recoveryCorrelation': row.intent.recovery_correlation,
                   'evidenceRef': row.evidence['evidenceRef']} for row in steps), (source(provider, 'access'),))


@pytest.fixture
def flow(tmp_path):
    owner = FixtureOwner()
    owner.store = store = SqliteStorePort(tmp_path / 'core.sqlite')
    env = Environment('env', store=store, policy=Policy(), principal_scope='principal',
        fingerprint_port=ProtectedFingerprintHmac({'fixture': b'controlled-family'}, active_key_id='fixture'))
    owner.request = RequestKey('env', 'principal', 'prepare-codex')
    owner.directory = DirectoryBindingRef('env', 'directory', 1, 'sha256:' + 'd' * 64)
    owner.current = CurrentState(None, owner.directory, None)
    owner.authority = Authority()
    owner.issuer = InvocationIssuer(store, owner.authority, owner.current, clock=lambda: 50)
    owner.roots = {'cwd': str(tmp_path / 'controlled-root')}
    owner.journal = OperationJournal(tmp_path / 'owner.sqlite')
    verifier = owner.issuer.verifier()
    owner.records = UnitRecords(owner.journal, scope_authority=owner, native_evidence=owner,
                                verifier=verifier, epoch_port=owner)
    owner.client = NativeClient()
    owner.opens = 0
    def open_channel(roots, facts):
        assert safe_json(roots) == safe_json(owner.roots)
        owner.opens += 1
        return owner.client
    owner.provider = CodexRuntimeProvider(definition_ref={'environmentNamespace': 'env', 'definitionId': 'codex', 'revision': '1'},
        implementation_digest='sha256:' + 'a' * 64, unit_records=owner.records, projection=owner,
        verifier=verifier, channel_factory=SimpleNamespace(open=open_channel))
    env.install(InstallationRecord('codex-plugin', 'a' * 64)); env.enable('codex-plugin')
    env.activate('codex-plugin', AgentContributionSet(agent_runtime_providers=(owner.provider,)))
    owner.current.provider = env.agent_runtime_contribution(owner.provider.descriptor.definition_ref).provider_ref
    catalog = ProfileCatalog(env)
    profile = catalog.create(profile_id='codex', display_name='Controlled Codex', manifest={
        'harnessDefinitionRef': dict(owner.provider.descriptor.definition_ref), 'schemaVersion': '1', 'declarations': []},
        request=RequestKey('env', 'principal', 'profile'))
    owner.nodes = NodePublication(env, evidence_port=owner)
    owner.assembly = AgentAssembly(env, catalog, owner.nodes, invocation_issuer=owner.issuer,
                                  context_port=owner, observation_port=owner)
    owner.profile = profile.current_manifest_ref
    yield owner
    store.close()


def test_actual_family_original_journal_and_core_publish_same_unit(flow):
    op = flow.assembly.prepare(flow.request, flow.profile, {}, {})
    assert op.status == 'published'
    unit = flow.original_unit()
    node = flow.nodes.read(decode_node_ref(op.intent.node_ref))
    assert node['binding']['harnessUnitRef'] == unit.public_ref
    assert node['binding']['configurationTargetRef'] == unit.configuration_target_ref
    assert flow.client.calls == ['initialize', 'thread/start', 'thread/read']
    assert flow.opens == 1
    assert flow.assembly.prepare(flow.request, flow.profile, {}, {}) == op
    assert flow.opens == 1


def test_receipt_loss_keeps_original_unknown_without_second_native_launch(flow):
    flow.client.fail = True
    op = flow.assembly.prepare(flow.request, flow.profile, {}, {})
    assert op.status == 'unknown' and flow.nodes.list() == ()
    unit = flow.original_unit()
    assert flow.read_session(unit.public_ref).state == 'unknown'
    assert flow.assembly.prepare(flow.request, flow.profile, {}, {}).status == 'unknown'
    assert flow.assembly.query(flow.request).status == 'unknown'
    assert flow.opens == 1 and flow.client.calls == ['initialize', 'thread/start']


def test_changed_request_after_publication_cannot_create_another_native_unit(flow):
    from ordessa_environment_api import IdentityMismatchError
    flow.assembly.prepare(flow.request, flow.profile, {}, {})
    with pytest.raises(IdentityMismatchError):
        flow.assembly.prepare(flow.request, flow.profile, {}, {'changed': True})
    assert flow.opens == 1 and flow.client.calls == ['initialize', 'thread/start', 'thread/read']


def test_native_readback_mismatch_never_confirms_original_binding(flow):
    flow.client.observed_id = 'replacement-thread'
    op = flow.assembly.prepare(flow.request, flow.profile, {}, {})
    assert op.status == 'unknown' and flow.nodes.list() == ()
    unit = flow.original_unit()
    assert flow.read_session(unit.public_ref).state == 'unknown'
    assert flow.assembly.prepare(flow.request, flow.profile, {}, {}).status == 'unknown'
    assert flow.opens == 1


def test_prepare_receipt_loss_queries_original_unit_without_starting_missing_step(flow, monkeypatch):
    reserve = flow.records.reserve_unit
    calls = []
    def lose_reply(*args, **kwargs):
        unit, created = reserve(*args, **kwargs)
        calls.append(unit.unit_ref)
        raise ConnectionError('controlled loss after persisted reservation')
    monkeypatch.setattr(flow.records, 'reserve_unit', lose_reply)
    assert flow.assembly.prepare(flow.request, flow.profile, {}, {}).status == 'unknown'
    assert flow.opens == 0 and flow.client.calls == [] and len(calls) == 1
    assert flow.assembly.query(flow.request).status == 'running'
    assert flow.store.read_operation_step(flow.request, 'start') is None
    assert flow.opens == 0 and flow.client.calls == [] and len(calls) == 1
    op = flow.assembly.prepare(flow.request, flow.profile, {}, {})
    assert op.status == 'published' and len(calls) == 1 and flow.opens == 1
    assert flow.original_unit().unit_ref == calls[0]


def test_other_authorized_request_cannot_escape_unknown_physical_scope(flow, monkeypatch):
    from ordessa_harness.application.unit_records import UnitRecordsRefused
    flow.client.fail = True
    original_request = flow.request
    assert flow.assembly.prepare(original_request, flow.profile, {}, {}).status == 'unknown'
    reserve = flow.records.reserve_unit
    refusals = []
    def observe_refusal(*args, **kwargs):
        try:
            return reserve(*args, **kwargs)
        except UnitRecordsRefused as error:
            refusals.append(str(error))
            raise
    monkeypatch.setattr(flow.records, 'reserve_unit', observe_refusal)
    # A different authenticated request in the SAME fixture realm, not a
    # resolve assertion or a core same-key replay short circuit.
    flow.request = RequestKey('env', 'principal', 'second-prepare')
    assert flow.assembly.prepare(flow.request, flow.profile, {}, {}).status == 'unknown'
    assert refusals == ['configuration scope already reserved']
    assert flow.store.read_operation(original_request).status == 'unknown'
    assert flow.opens == 1 and flow.client.calls == ['initialize', 'thread/start']
    with flow.journal._connect() as db:
        assert db.execute('SELECT COUNT(*) FROM harness_unit_reservations').fetchone()[0] == 1
        assert db.execute('SELECT state FROM harness_unit_sessions').fetchone()['state'] == 'unknown'


@pytest.mark.parametrize('change', ['authority', 'activation', 'directory', 'epoch'])
def test_revoke_between_initialize_and_thread_start_blocks_next_native_edge(flow, change):
    def revoke():
        if change == 'authority': flow.authority.allowed = False
        elif change == 'activation': flow.current.active = False
        elif change == 'directory': flow.current.permitted = False
        else: flow.current.epoch += 1
    flow.client.after_initialize = revoke
    op = flow.assembly.prepare(flow.request, flow.profile, {}, {})
    assert op.status == 'unknown' and flow.nodes.list() == ()
    assert flow.opens == 1 and flow.client.calls == ['initialize']
    with flow.journal._connect() as db:
        row = db.execute('SELECT state FROM harness_unit_sessions').fetchone()
    # Epoch revocation also prevents the old record ticket from writing an
    # unknown observation; opening itself still retains the original fence.
    assert row['state'] == ('opening' if change == 'epoch' else 'unknown')
