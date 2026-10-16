"""Codex declaration compiler only; no native process, model, files or effects."""
from dataclasses import replace

import pytest
from ordessa_execution_api.environment import (
    AdmissionRefusedError, GuaranteeUnavailableError, IdentityMismatchError)
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


@pytest.fixture
def public_read_world(tmp_path):
    from types import SimpleNamespace
    from ordessa_units.admission.context import UnitAdmissionContext
    from ordessa_units.admission.material_registration import MaterialCatalog
    from ordessa_units.persistence.sqlite.store import SqliteUnitStore
    from ordessa_execution_agents.harness.providers.registry import (
        HarnessCatalog, HarnessDefinitionDescriptor, HarnessDefinitionDeclaration,
        HarnessInstallationObservation)
    class Policy:
        refused = False
        def admit_object_access(self, principal, target, access):
            return not (self.refused and target == 'pure-codex:agents.definition:codex')
    policy = Policy()
    store = SqliteUnitStore(tmp_path / 'original.sqlite')
    holder = []
    catalog = HarnessCatalog('pure-codex', policy=policy, principal_scope='authenticated-test',
        retirement_guard=lambda owner, generation: holder[0].provider_retirement_guard(owner, generation))
    descriptor = HarnessDefinitionDescriptor('codex', DEF, DIGEST, 'codex-app-server/v2', 'controlled')
    declaration = HarnessDefinitionDeclaration(descriptor,
        lambda ref: HarnessInstallationObservation('unknown'))
    catalog.stage('codex-plugin', 1, 'controlled', 'a' * 64, (declaration,)).commit()
    env = UnitAdmissionContext('pure-codex', store=store, policy=policy, fingerprint_port=None,
        harness_catalog=catalog, material_catalog=MaterialCatalog('pure-codex'),
        principal_scope='authenticated-test')
    holder.append(env)
    provider, _ = fixture()
    yield SimpleNamespace(env=env, store=store, catalog=catalog, declaration=declaration,
                          policy=policy, provider=provider)
    env.close()
    store.close()


def test_original_public_core_routes_read_and_enforces_read_permission(public_read_world):
    from ordessa_units.public import unit_services, bind_configuration_offer_compiler
    world = public_read_world
    env, provider, policy = world.env, world.provider, world.policy
    binding = bind_configuration_offer_compiler(env, provider)
    api = unit_services(env, configuration_offer_compiler=binding)
    offers = api.configuration_offers.describe_configuration_offers(DEF)
    value = replace(proposal(), provider_ref=offers.owner_ref)
    result = api.configuration_offers.assess_configuration_proposal(value)
    assert result.status == 'valid'
    policy.refused = True
    with pytest.raises(AdmissionRefusedError): api.configuration_offers.describe_configuration_offers(DEF)
    with pytest.raises(AdmissionRefusedError): api.configuration_offers.assess_configuration_proposal(value)
    assert provider._channels == {} and provider._configuration_waiters == {}


def test_declaration_without_explicit_compiler_remains_unavailable(public_read_world):
    from ordessa_units.public import unit_services
    with pytest.raises(GuaranteeUnavailableError, match='compiler owner is not bound'):
        unit_services(public_read_world.env).configuration_offers.describe_configuration_offers(DEF)
    assert public_read_world.provider._channels == {}


def test_compiler_binding_cannot_move_to_an_identical_other_context(public_read_world, tmp_path):
    from ordessa_units.public import unit_services, bind_configuration_offer_compiler
    from ordessa_units.admission.context import UnitAdmissionContext
    world = public_read_world
    binding = bind_configuration_offer_compiler(world.env, world.provider)
    other = UnitAdmissionContext('pure-codex', store=world.store, policy=world.policy,
        fingerprint_port=None, harness_catalog=world.catalog,
        material_catalog=world.env.material_catalog, principal_scope='authenticated-test')
    with pytest.raises(IdentityMismatchError, match='another admission context'):
        unit_services(other, configuration_offer_compiler=binding)
    assert other._agent_services is None


def test_compiler_selection_cannot_replace_a_published_service_owner(public_read_world):
    from ordessa_units.public import unit_services, bind_configuration_offer_compiler
    world = public_read_world
    first = bind_configuration_offer_compiler(world.env, world.provider)
    api = unit_services(world.env, configuration_offer_compiler=first)
    second = bind_configuration_offer_compiler(world.env, world.provider)
    with pytest.raises(ValueError, match='selected once'):
        unit_services(world.env, configuration_offer_compiler=second)
    assert unit_services(world.env, configuration_offer_compiler=first) is api


def test_compiler_descriptor_drift_is_refused_before_read_callback(public_read_world, monkeypatch):
    from ordessa_units.public import unit_services, bind_configuration_offer_compiler
    world = public_read_world
    binding = bind_configuration_offer_compiler(world.env, world.provider)
    api = unit_services(world.env, configuration_offer_compiler=binding)
    monkeypatch.setattr(world.provider, 'descriptor', None)
    with pytest.raises(GuaranteeUnavailableError, match='compiler owner changed'):
        api.configuration_offers.describe_configuration_offers(DEF)


def test_replaced_admission_generation_never_reuses_old_compiler(public_read_world):
    from ordessa_units.public import unit_services, bind_configuration_offer_compiler
    world = public_read_world
    binding = bind_configuration_offer_compiler(world.env, world.provider)
    api = unit_services(world.env, configuration_offer_compiler=binding)
    world.catalog.drain('codex-plugin', 1)
    world.catalog.retire('codex-plugin', 1)
    world.catalog.stage('codex-plugin', 2, 'controlled', 'a' * 64, (world.declaration,)).commit()
    with pytest.raises(GuaranteeUnavailableError, match='compiler owner changed'):
        api.configuration_offers.describe_configuration_offers(DEF)


def test_policy_cut_during_compilation_rejects_the_computed_result(public_read_world, monkeypatch):
    from ordessa_units.public import unit_services, bind_configuration_offer_compiler
    world = public_read_world
    original = world.provider.describe_configuration_offers
    def read_then_cut(*args):
        result = original(*args)
        world.policy.refused = True
        return result
    monkeypatch.setattr(world.provider, 'describe_configuration_offers', read_then_cut)
    binding = bind_configuration_offer_compiler(world.env, world.provider)
    api = unit_services(world.env, configuration_offer_compiler=binding)
    with pytest.raises(AdmissionRefusedError, match='read refused'):
        api.configuration_offers.describe_configuration_offers(DEF)
    assert world.provider._channels == {} and world.provider._configuration_waiters == {}
    with world.store.transaction() as db:
        assert db.execute('SELECT COUNT(*) FROM env_requests').fetchone()[0] == 0


def test_closed_original_context_cannot_read_bound_compiler(public_read_world):
    from ordessa_units.public import unit_services, bind_configuration_offer_compiler
    world = public_read_world
    binding = bind_configuration_offer_compiler(world.env, world.provider)
    api = unit_services(world.env, configuration_offer_compiler=binding)
    world.env.close()
    with pytest.raises(AdmissionRefusedError, match='closed'):
        api.configuration_offers.describe_configuration_offers(DEF)


def test_compiler_descriptor_drift_during_read_rejects_result(public_read_world, monkeypatch):
    from ordessa_units.public import unit_services, bind_configuration_offer_compiler
    world = public_read_world
    original = world.provider.describe_configuration_offers
    def read_then_drift(*args):
        result = original(*args)
        world.provider.descriptor = replace(world.provider.descriptor,
            implementation_digest='sha256:' + 'f' * 64)
        return result
    monkeypatch.setattr(world.provider, 'describe_configuration_offers', read_then_drift)
    binding = bind_configuration_offer_compiler(world.env, world.provider)
    api = unit_services(world.env, configuration_offer_compiler=binding)
    with pytest.raises(GuaranteeUnavailableError, match='compiler owner changed'):
        api.configuration_offers.describe_configuration_offers(DEF)


def test_compiler_binding_checks_exact_declared_implementation(public_read_world, monkeypatch):
    from ordessa_units.public import bind_configuration_offer_compiler
    world = public_read_world
    monkeypatch.setattr(world.provider, 'descriptor', replace(world.provider.descriptor,
        implementation_digest='sha256:' + 'f' * 64))
    with pytest.raises(IdentityMismatchError, match='differs from admitted definition'):
        bind_configuration_offer_compiler(world.env, world.provider)
    assert world.provider._channels == {} and world.provider._configuration_waiters == {}
