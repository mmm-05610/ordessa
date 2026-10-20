"""Current Profile/Harness reads and original proposal-mapping negative guarantees.

No historical graph or Unit runtime is assembled. Test-owned proposal assessment
is a pure port witness, not a production configuration-definition owner.
"""
import asyncio
import hashlib
import json
import subprocess
import sys
from dataclasses import replace
from types import SimpleNamespace

import pytest
from decision_runtime.historical.context import ReadContext
from decision_runtime.historical.models import ProposalDraft, ValidationObligation, ExternalRef
from decision_runtime.historical.values import ContractError, plain
from ordessa_execution_agents.harness.providers.catalog import HarnessCatalog
from ordessa_execution_agents.sdk.harness import HarnessDescriptor, HarnessError
from ordessa_system_access_bindings.decision import (
    ReadOwners, OrdessaReadFacade, ObservationQuery, OwnerProposalValidator,
)
from ordessa_units.configuration.proposal_input import OwnerProposalInput
from apps.cli.tests.integration.profile_test_owner import profile_owner

DEF = {'environmentNamespace': 'test', 'definitionId': 'fixture', 'revision': '1'}


@pytest.fixture
def owner(tmp_path):
    class Policy:
        allowed = True
        filter_items = False
        def admit_invoke(self, *args): return self.allowed
        def admit_object_access(self, principal, identity, action):
            return self.allowed and (not self.filter_items or identity.endswith(":*"))
    policy = Policy()
    original = profile_owner(tmp_path / 'profiles.sqlite', 'test', 'principal:test', policy, DEF)
    yield original, policy
    original.close()


def catalog():
    def forbidden(*args): raise AssertionError('owner effect or validation must not run during descriptor read')
    provider = SimpleNamespace(descriptor=HarnessDescriptor('fixture', DEF, 'sha256:'+'a'*64, None, (), ()),
        validate_profile=forbidden, prepare=forbidden, open_session=forbidden)
    return HarnessCatalog([provider]), provider


def observe(adapter, kind, context, params=None):
    return asyncio.run(adapter.observe(ObservationQuery(kind, {} if params is None else params), context))


def test_original_profile_ref_filtered_scope_and_real_owner_denial(owner, tmp_path, monkeypatch):
    original, policy = owner
    context = ReadContext(object(), 'test')
    adapter = OrdessaReadFacade(ReadOwners(profiles=original.service), namespace='test', read_context=context)
    profile = original.service.create(profile_id='sample', name='Sample', content={
        'harnessDefinitionRef': DEF, 'schemaVersion': '1', 'declarations': []},
        request=original.service.request_key('create'))
    from ordessa_execution_agents.profiles import encode_revision_ref
    def snapshot():
        return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in tmp_path.rglob('*') if path.is_file()}
    before = snapshot()
    def forbidden_process(*args, **kwargs): raise AssertionError('read must not start processes')
    monkeypatch.setattr(subprocess, 'Popen', forbidden_process)
    listed = observe(adapter, 'profiles', context)
    assert not listed.complete and listed.unobserved_items == ('permission_filtered_items',)
    assert len(listed.observations) == 1
    ref = encode_revision_ref(profile.current_revision)
    single = observe(adapter, 'profile', context, {'profile_ref': ref})
    assert single.complete and single.observations[0].source_version == '1'
    assert plain(single.observations[0].data)['profileRef'] == ref
    with pytest.raises(ContractError, match='read_refused'):
        observe(adapter, 'profiles', ReadContext(object(), 'test'))
    with pytest.raises(ContractError, match='read_refused'):
        observe(adapter, 'profiles', ReadContext(context.authority, 'other'))
    policy.filter_items = True
    # The actual Profile owner can filter per-item access. Empty is still not absence.
    filtered = observe(adapter, 'profiles', context)
    assert not filtered.complete and filtered.unobserved_items == ('permission_filtered_items',)
    assert not filtered.observations
    from ordessa_execution_agents.profiles import ProfileAccessRefused
    with pytest.raises(ProfileAccessRefused): observe(adapter, 'profile', context, {'profile_ref': ref})
    policy.allowed = False
    with pytest.raises(ProfileAccessRefused): observe(adapter, 'profiles', context)
    assert snapshot() == before


def test_harness_projection_is_actual_pin_without_fabricated_admission():
    harnesses, provider = catalog()
    context = ReadContext(object(), 'test')
    adapter = OrdessaReadFacade(ReadOwners(harnesses=harnesses), namespace='test', read_context=context)
    batch = observe(adapter, 'providers', context)
    assert not batch.complete and 'installation' in batch.unobserved_items
    assert 'provider_admission' in batch.unobserved_items
    value = plain(batch.observations[0].data)
    assert value == provider.descriptor.projection() and 'providerRef' not in value
    provider.descriptor = replace(provider.descriptor, implementation_digest='sha256:'+'b'*64)
    with pytest.raises(HarnessError, match='HARNESS_PIN_CHANGED'): observe(adapter, 'providers', context)


def test_profile_truncation_does_not_claim_complete(owner):
    original, _ = owner
    for i in range(2):
        original.service.create(profile_id='sample'+str(i), name='Sample', content={
            'harnessDefinitionRef': DEF, 'schemaVersion': '1', 'declarations': []},
            request=original.service.request_key('create'+str(i)))
    context = ReadContext(object(), 'test')
    adapter = OrdessaReadFacade(ReadOwners(profiles=original.service), namespace='test', read_context=context, max_items=1)
    batch = observe(adapter, 'profiles', context)
    assert not batch.complete and len(batch.observations) == 1
    assert plain(batch.pagination) == {'truncated': True, 'count': 1}


@pytest.mark.parametrize(('kind', 'params', 'error'), [
    ('nodes', {}, 'agent_inventory_owner_unbound'),
    ('configuration', {'node_ref': {}}, 'instance_configuration_read_owner_unbound'),
    ('configuration_offers', {'definition_ref': DEF}, 'configuration_definition_owner_unbound'),
    ('profiles', {}, 'profile_owner_unbound'),
    ('providers', {}, 'harness_catalog_unbound'),
])
def test_missing_owners_refuse_instead_of_fabricating_observation(kind, params, error):
    context = ReadContext(object(), 'test')
    adapter = OrdessaReadFacade(ReadOwners(), namespace='test', read_context=context)
    with pytest.raises(ContractError, match=error): observe(adapter, kind, context, params)


def test_query_and_binding_negative_guarantees():
    context = ReadContext(object(), 'test')
    with pytest.raises(ContractError): ObservationQuery('assembly.prepare', {})
    with pytest.raises(ContractError): ObservationQuery('profiles', [])
    with pytest.raises(ContractError): OrdessaReadFacade(SimpleNamespace(), namespace='test', read_context=context)
    with pytest.raises(ContractError): ReadOwners(profiles=object())
    adapter = OrdessaReadFacade(ReadOwners(), namespace='test', read_context=context)
    with pytest.raises(ContractError, match='query_parameters'): observe(adapter, 'nodes', context, {'unexpected': 1})


def proposal():
    obligation = ValidationObligation('config', ExternalRef('test', DEF), 'must', 'owner', '1')
    return ProposalDraft('proposal', 'configuration', {'ratio': 0.7}, required_validation_obligations=(obligation,))


def value_for(draft, ratio=0.7):
    return OwnerProposalInput(DEF, DEF, '1', {'configurationKind': 'brand.new', 'payload': ratio}, (),
        tuple({'obligationId': o.obligation_id, 'requirement': o.requirement,
            'checkerId': o.validator_kind, 'checkerVersion': o.version_constraint}
            for o in draft.required_validation_obligations))


class AssessmentPort:
    def __init__(self, *, bad_digest=False, missing_evidence=False):
        self.calls = []
        self.bad_digest = bad_digest
        self.missing_evidence = missing_evidence
    def assess_configuration_proposal(self, value):
        self.calls.append(value)
        return SimpleNamespace(input_digest='bad' if self.bad_digest else value.input_digest,
            status='valid', obligation_results=tuple({'obligationId': o['obligationId'], 'status': 'passed',
                'checkerId': o['checkerId'], 'checkerVersion': o['checkerVersion'],
                'sourceVersions': {'descriptor': '1'}, 'evidenceRefs': [] if self.missing_evidence else [{'evidenceId': 'controlled'}]}
                for o in value.required_obligations), validation_scope='controlled pure read', source_versions={'descriptor': '1'}, issues=())


@pytest.mark.parametrize('ratio', [0.1, 0.9])
def test_original_wrong_semantic_mapping_rejected_before_owner(ratio):
    context = ReadContext(object(), 'test'); port = AssessmentPort(); draft = proposal()
    validator = OwnerProposalValidator(port, input_builder=lambda d, b: value_for(d, ratio), read_context=context,
        input_verifier=lambda d, b, value: value.proposal_data['payload'] == d.payload['ratio'])
    with pytest.raises(ContractError, match='owner_mapping_mismatch'):
        asyncio.run(validator.validate(draft, {}, context))
    assert not port.calls


@pytest.mark.parametrize('error', ['owner_mapping_unverified', 'owner_obligation_mapping', 'owner_input'])
def test_original_preowner_checks_preserved(error):
    context = ReadContext(object(), 'test'); port = AssessmentPort(); draft = proposal()
    def builder(d, b):
        value = value_for(d)
        return object() if error == 'owner_input' else replace(value, required_obligations=()) if error == 'owner_obligation_mapping' else value
    validator = OwnerProposalValidator(port, input_builder=builder, read_context=context,
        input_verifier=None if error == 'owner_mapping_unverified' else lambda *args: True)
    with pytest.raises(ContractError, match=error): asyncio.run(validator.validate(draft, {}, context))
    assert not port.calls


@pytest.mark.parametrize(('bad_digest', 'missing_evidence', 'error'), [(True, False, 'owner_digest_mismatch'), (False, True, 'obligation_unverified')])
def test_original_digest_and_required_evidence_checks(bad_digest, missing_evidence, error):
    context = ReadContext(object(), 'test'); port = AssessmentPort(bad_digest=bad_digest, missing_evidence=missing_evidence)
    validator = OwnerProposalValidator(port, input_builder=lambda d, b: value_for(d), read_context=context, input_verifier=lambda *args: True)
    with pytest.raises(ContractError, match=error): asyncio.run(validator.validate(proposal(), {}, context))
    assert len(port.calls) == 1


def test_original_receipt_positive_and_authority_negatives():
    context = ReadContext(object(), 'test'); port = AssessmentPort(); draft = proposal()
    validator = OwnerProposalValidator(port, input_builder=lambda d, b: value_for(d), read_context=context, input_verifier=lambda *args: True)
    receipt = asyncio.run(validator.validate(draft, {}, context))
    assert receipt.status == 'valid' and receipt.proposal_digest == draft.proposal_digest
    assert receipt.validator_id == 'ordessa.owner' and len(port.calls) == 1
    for wrong in (ReadContext(object(), 'test'), ReadContext(context.authority, 'other'), object()):
        with pytest.raises(ContractError, match='read_refused'): asyncio.run(validator.validate(draft, {}, wrong))
    assert len(port.calls) == 1


def test_isolated_import_avoids_unit_online_and_graph():
    code = """import sys,json
sys.path[:0]=json.loads(sys.argv[1])
from ordessa_system_access_bindings.decision import OrdessaReadFacade,OwnerProposalValidator
for n in ('ordessa_units.public','ordessa_units.configuration.offers','ordessa_units.api','decision_runtime.runtime','decision_runtime.runtime.manager','decision_runtime.flows'):
 assert n not in sys.modules,n
"""
    result = subprocess.run([sys.executable, '-I', '-S', '-c', code, json.dumps(sys.path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
