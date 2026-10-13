"""Codex declaration compiler only; no native process, model, files or effects."""
from dataclasses import replace

import pytest
from ordessa_execution_api.environment.operations import safe_json
from ordessa_harness_codex import CodexRuntimeProvider, CodexProviderRefused
from ordessa_harness_codex.provider import DEFAULTS_SCHEMA, DEFAULT_FIELDS
from ordessa_units.public import (
    OwnerReadContext, OwnerProposalInput, PURE_READ_VERSION, RUNTIME_PROVIDER_VERSION,
)
from ordessa_units.configuration.offers import require_assessment

DEF = {'environmentNamespace': 'pure-codex', 'definitionId': 'codex', 'revision': '1'}
DIGEST = 'sha256:' + 'a' * 64
OWNER = {'environmentNamespace': 'pure-codex', 'providerId': 'codex', 'generation': 1,
    'implementationDigest': DIGEST, 'contractVersion': RUNTIME_PROVIDER_VERSION,
    'ownerActivationRef': {'environmentNamespace': 'pure-codex', 'pluginId': 'codex-plugin', 'generation': 1}}

FORBIDDEN_METHODS = ('inspect_configuration', '_read_configuration', 'start', 'prepare', 'connect',
    'apply_configuration', '_facts', '_unit', 'inspect_unit', 'inspect_installation', 'query_change', 'stop', 'release', 'recover')


@pytest.fixture(autouse=True)
def zero_native_effect_calls(monkeypatch):
    """Count forbidden edges even if a business-invalid path catches the guard."""
    original = CodexRuntimeProvider.__init__; trackers = []
    def initialise(provider, *args, **kwargs):
        original(provider, *args, **kwargs)
        counts = {name: 0 for name in FORBIDDEN_METHODS}; trackers.append(counts)
        for name in FORBIDDEN_METHODS:
            def forbidden(*args, _name=name, _counts=counts, **kwargs):
                _counts[_name] += 1
                raise AssertionError('native/effect path forbidden: ' + _name)
            monkeypatch.setattr(provider, name, forbidden)
    monkeypatch.setattr(CodexRuntimeProvider, '__init__', initialise)
    yield
    for counts in trackers: assert counts == {name: 0 for name in FORBIDDEN_METHODS}


def fixture():
    provider = CodexRuntimeProvider(definition_ref=DEF, implementation_digest=DIGEST)
    context = OwnerReadContext('pure-codex', OWNER, 'authenticated-test')
    return provider, context


def declaration(**changes):
    result = {'declarationId': 'defaults', 'configurationKind': 'codex.defaults', 'schemaVersion': DEFAULTS_SCHEMA,
        'action': 'value', 'requirement': 'required', 'payload': {'model': 'synthetic-model', 'model_reasoning_effort': 'high'}}
    result.update(changes); return result


def proposal(declarations=None, obligations=None, sources=()):
    declarations = [declaration()] if declarations is None else declarations
    obligations = ({'obligationId': 'compile', 'requirement': 'must', 'checkerId': 'codex.defaults.compile', 'checkerVersion': DEFAULTS_SCHEMA},) if obligations is None else obligations
    return OwnerProposalInput(DEF, OWNER, '1', {'declarations': declarations}, sources, obligations)


def test_offer_is_unknown_and_schema_matches_original_owner_description():
    provider, context = fixture()
    offers = provider.describe_configuration_offers(DEF, context)
    assert provider.descriptor.pure_read_contract_version == PURE_READ_VERSION
    assert offers.owner_ref == context.provider_ref and offers.descriptor_digest == DIGEST
    assert offers.complete is False and set(offers.unknown_items) == {'installation', 'runtimeReady', 'unit', 'application', 'effect', 'credentials'}
    offer = offers.offers[0]
    assert offer.support_status == 'unknown' and offer.scope == 'instance'
    assert offer.supported_actions == ('value', 'reset') and offer.application_modes == () and offer.confirmation == 'none'
    assert offer.input_schema['minProperties'] == 1
    assert offer.input_schema['properties']['model']['maxLength'] == 256
    assert provider._channels == {} and provider._configuration_waiters == {}


def test_exact_compile_obligation_and_source_versions_are_bound_without_effects():
    provider, context = fixture()
    source = {'environmentNamespace': 'pure-codex', 'profileId': 'p', 'manifestRevision': 3, 'contentDigest': 'sha256:' + 'b' * 64}
    value = proposal(sources=(source,)); result = provider.assess_configuration_proposal(value, context)
    require_assessment(value, result)
    assert result.status == 'valid' and result.input_digest == value.input_digest
    assert result.validation_scope == 'codex.defaults.declaration-compile/' + DEFAULTS_SCHEMA
    assert result.source_versions == {'descriptor': '1', safe_json(source): 3}
    row = result.obligation_results[0]
    assert row['status'] == 'passed' and row['sourceVersions'] == result.source_versions
    assert row['evidenceRefs'][0]['inputDigest'] == value.input_digest
    assert row['evidenceRefs'][0]['durability'] == 'computed_nonpersistent'
    assert provider._channels == {} and provider._configuration_waiters == {}


@pytest.mark.parametrize('obligations', [(),
    ({'obligationId': 'unknown', 'requirement': 'must', 'checkerId': 'native.application', 'checkerVersion': '1'},),
    ({'obligationId': 'compile', 'requirement': 'must', 'checkerId': 'codex.defaults.compile', 'checkerVersion': 'other'},),
    ({'obligationId': 'advisory', 'requirement': 'advisory', 'checkerId': 'codex.defaults.compile', 'checkerVersion': DEFAULTS_SCHEMA},),
])
def test_no_exact_must_obligation_never_becomes_valid(obligations):
    provider, context = fixture()
    assert provider.assess_configuration_proposal(proposal(obligations=obligations), context).status == 'unverifiable'


def test_advisory_unknown_does_not_block_known_must_or_claim_coverage():
    provider, context = fixture(); value = proposal()
    unknown = {'obligationId': 'availability', 'requirement': 'advisory', 'checkerId': 'installation.available', 'checkerVersion': '1'}
    result = provider.assess_configuration_proposal(replace(value, required_obligations=value.required_obligations + (unknown,)), context)
    assert result.status == 'valid' and result.obligation_results[1]['status'] == 'unknown'
    assert result.obligation_results[1]['evidenceRefs'] == ()


def test_known_must_and_unknown_must_is_unverifiable():
    provider, context = fixture(); value = proposal()
    unknown = {'obligationId': 'native', 'requirement': 'must', 'checkerId': 'native.application', 'checkerVersion': '1'}
    result = provider.assess_configuration_proposal(replace(value, required_obligations=value.required_obligations + (unknown,)), context)
    assert result.status == 'unverifiable'
    assert [row['status'] for row in result.obligation_results] == ['passed', 'unknown']


@pytest.mark.parametrize('error', [AssertionError, RuntimeError])
def test_internal_compiler_fault_propagates_instead_of_business_invalid(monkeypatch, error):
    provider, context = fixture()
    def fault(change): raise error('internal compiler fault')
    monkeypatch.setattr(provider, '_compile_change', fault)
    with pytest.raises(error, match='internal compiler fault'):
        provider.assess_configuration_proposal(proposal(), context)


@pytest.mark.parametrize('declarations', [[],
    [declaration(payload={'model': 'bad\ncontrol'})],
    [declaration(payload={'unknown_field': 'value'})],
    [declaration(schemaVersion='unknown')],
    [declaration(), declaration()],
    [declaration(), declaration(declarationId='overlap')],
    [declaration(extraField=True)],
])
def test_original_dto_or_compiler_rejection_returns_invalid(declarations):
    provider, context = fixture()
    result = provider.assess_configuration_proposal(proposal(declarations), context)
    assert result.status == 'invalid' and result.obligation_results[0]['status'] == 'failed'


def test_optional_unsupported_is_skipped_and_reset_retains_original_full_field_semantics():
    provider, context = fixture()
    optional = declaration(declarationId='optional', requirement='optional', payload={'unknown': 'field'})
    result = provider.assess_configuration_proposal(proposal([declaration(), optional]), context)
    assert result.status == 'valid'
    assert any(v['code'] == 'codex_defaults_optional_declarations_skipped' and list(v['declarationIds']) == ['optional'] for v in result.issues)
    reset = declaration(action='reset'); reset.pop('payload')
    result = provider.assess_configuration_proposal(proposal([reset]), context)
    assert result.status == 'valid'
    from ordessa_units.public import ConfigurationChangeRequest
    edits, _, _ = provider._compile_change(ConfigurationChangeRequest('reset', '1', (reset,)))
    assert {e['keyPath'] for e in edits} == DEFAULT_FIELDS and all(e['value'] is None for e in edits)


def test_reset_then_value_overlapping_field_is_invalid():
    provider, context = fixture()
    reset = declaration(action='reset'); reset.pop('payload')
    value = declaration(declarationId='after-reset', payload={'model': 'synthetic-new'})
    result = provider.assess_configuration_proposal(proposal([reset, value]), context)
    assert result.status == 'invalid' and result.obligation_results[0]['status'] == 'failed'


@pytest.mark.parametrize('change', ['bare', 'namespace', 'implementation', 'provider', 'generation', 'descriptor', 'source_bool'])
def test_context_owner_and_source_refusals(change):
    provider, context = fixture(); value = proposal()
    if change == 'bare': context = {'principal': 'authenticated'}
    elif change == 'namespace': context = OwnerReadContext('foreign', dict(OWNER, environmentNamespace='foreign'), 'test')
    elif change in ('implementation', 'provider', 'generation'):
        owner = dict(OWNER)
        owner[{'implementation': 'implementationDigest', 'provider': 'providerId', 'generation': 'generation'}[change]] = {'implementation': 'sha256:' + 'c' * 64, 'provider': 'pi', 'generation': True}[change]
        context = OwnerReadContext('pure-codex', owner, 'test')
    elif change == 'descriptor': value = replace(value, descriptor_revision='2')
    else: value = replace(value, source_refs=({'environmentNamespace': 'pure-codex', 'profileId': 'p', 'manifestRevision': True},))
    with pytest.raises(CodexProviderRefused): provider.assess_configuration_proposal(value, context)


def test_original_public_core_routes_read_and_enforces_read_permission():
    from pacthold.public import Environment, InstallationRecord
    from ordessa_units.public import AgentContributionSet, unit_services
    from ordessa_execution_api.environment import AdmissionRefusedError
    class Policy:
        refused = False
        def admit_object_access(self, principal, target, access):
            return not (self.refused and target == 'pure-codex:agents.definition:codex')
    policy = Policy(); env = Environment('pure-codex', policy=policy, principal_scope='authenticated-test')
    try:
        env.install(InstallationRecord('codex-plugin', 'a' * 64)); env.enable('codex-plugin')
        provider, _ = fixture()
        env.activate('codex-plugin', AgentContributionSet(agent_runtime_providers=(provider,)))
        api = unit_services(env)
        offers = api.configuration_offers.describe_configuration_offers(DEF)
        value = replace(proposal(), provider_ref=offers.owner_ref)
        result = api.configuration_offers.assess_configuration_proposal(value)
        assert result.status == 'valid'
        policy.refused = True
        with pytest.raises(AdmissionRefusedError): api.configuration_offers.describe_configuration_offers(DEF)
        with pytest.raises(AdmissionRefusedError): api.configuration_offers.assess_configuration_proposal(value)
        assert provider._channels == {} and provider._configuration_waiters == {}
    finally: env.close()
