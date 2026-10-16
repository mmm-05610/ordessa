"""Claude Code server plugin build: one frozen definition declaration, never a fake grant.

The plugin publishes only the frozen ``HarnessDefinitionDeclaration`` at the
host's definition point. The retired provider factory and the owner-view wiring
it used are gone: no live owner, records, journal or native process is consumed
here. The assembled owner's records/verifier stay a real, refused-if-substituted
input to the provider a deployment composes — the positive (the exact assembled
pair is consumed) and negative (a substituted pair is refused) cases remain.
"""
from types import SimpleNamespace

import pytest

from ordessa_execution_agents.harness.providers.registry import (
    HARNESS_DEFINITION_VERSION,
    HarnessCatalog,
    HarnessDefinitionDeclaration,
    HarnessDefinitionDescriptor,
    HarnessInstallationObservation,
)
from ordessa_execution_api.environment import GuaranteeUnavailableError
from server_plugin_api import ServerPluginContext

from ordessa_harness_claude_code.provider import ClaudeCodeRuntimeProvider, ClaudeProviderUnavailable
from ordessa_harness_claude_code.server_plugin import ClaudeCodeServerPlugin

# Test fixture digest only — NOT a real implementation digest. Production
# digests are injected by the deployment fingerprint gate.
DIGEST = 'sha256:' + 'c' * 64
ENVIRONMENT_ID = 'env-claude-fixture'
DEFINITION = {'environmentNamespace': ENVIRONMENT_ID, 'definitionId': 'claude', 'revision': '1'}
POINT_ID = 'execution.harness.definitions'
DISCOVERY_METHODS = {'describe_definition', 'inspect_installation',
                     'assess_configuration', 'plan_preparation'}


class OwnerView:
    """Duck-typed deployment OwnerProviderView: records and verifier only."""

    def __init__(self, records, verifier):
        self.records, self.verifier = records, verifier


class ViewVerifier:
    """Idle verifier stand-in; identity object, grants nothing."""


class ViewUnitRecords:
    """Controlled contract stand-in: reserves nothing."""

    def __init__(self, verifier):
        self.verifier = verifier

    def reserve_unit(self, *args, **kwargs):
        raise AssertionError('controlled contract stand-in reserves nothing')


class Preparer:
    def verify_preparation(self, plan, facts):
        return True


def fresh_view():
    """One internally consistent owner view: records.verifier is THE verifier."""
    verifier = ViewVerifier()
    return OwnerView(records=ViewUnitRecords(verifier), verifier=verifier)


def live_provider(view):
    """The retired factory product: a live provider wired to one owner view."""
    return ClaudeCodeRuntimeProvider(definition_ref=DEFINITION, implementation_digest=DIGEST,
                                     unit_records=view.records, verifier=view.verifier,
                                     preparation_authority=Preparer())


class Policy:
    """Catalog access policy: registration may read, never invoke."""

    def admit_object_access(self, principal, obj, permission):
        return True

    def admit_invoke(self, *args):
        raise AssertionError('registration cannot mint authority')


def catalog(namespace=ENVIRONMENT_ID):
    return HarnessCatalog(namespace, policy=Policy(), principal_scope='controlled')


def context(namespace=ENVIRONMENT_ID, *, bound=True):
    """One catalog binding; `bound=False` states an absent catalog explicitly."""
    return ServerPluginContext(
        plugin_id='claude-code', data_root=None,
        ports={'execution.harness.catalog': catalog(namespace) if bound else None})


def declaration(*, namespace=ENVIRONMENT_ID, provider_id='claude', definition_id='claude', observer=None):
    """The frozen definition the deployment binds; never a live owner."""
    if observer is None:
        def observer(installation_ref):
            return HarnessInstallationObservation('present')
    return HarnessDefinitionDeclaration(HarnessDefinitionDescriptor(
        provider_id,
        {'environmentNamespace': namespace, 'definitionId': definition_id, 'revision': '1'},
        DIGEST, 'claude-agent-sdk', 'reviewed-adapter', backend_version='reviewed-native'), observer)


def registration_payload(registration):
    """The one contribution's frozen declaration, at the host definition point."""
    (contribution,) = registration.contributions.contributions
    assert contribution.point_id == POINT_ID
    assert contribution.api_version == HARNESS_DEFINITION_VERSION
    assert contribution.required is True
    return contribution.payload


def test_descriptor_reports_claude_code_identity():
    plugin = ClaudeCodeServerPlugin(declaration())
    descriptor = plugin.descriptor()
    assert descriptor.id == 'claude-code'
    assert descriptor.display_name == 'Independent ClaudeCode AgentUnit'
    assert descriptor.version == '0.1.0a1'


def test_registration_carries_the_frozen_declaration_metadata():
    frozen = declaration()
    registration = ClaudeCodeServerPlugin(frozen).build(context())
    payload = registration_payload(registration)
    # The native host contribution carries the frozen declaration opaquely.
    assert type(payload) is tuple and payload == (frozen,)
    descriptor = frozen.descriptor
    assert descriptor.provider_id == 'claude'
    assert dict(descriptor.definition_ref) == DEFINITION
    assert descriptor.implementation_digest == DIGEST
    assert descriptor.protocol_id == 'claude-agent-sdk'
    assert descriptor.adapter_version == 'reviewed-adapter'
    assert descriptor.backend_version == 'reviewed-native'


def test_registration_never_carries_a_live_owner_or_provider():
    """Only frozen declarations travel; a provider/records/verifier never does."""
    frozen = declaration()
    payload = registration_payload(ClaudeCodeServerPlugin(frozen).build(context()))
    view = fresh_view()
    provider = live_provider(view)
    # The provider consumes exactly the assembled owner's original records and verifier.
    assert provider._records is view.records and provider._verifier is view.verifier
    assert 'prepare' in provider.descriptor.supported_methods
    assert 'start' not in provider.descriptor.supported_methods
    # ... but no live owner ever enters the frozen registration payload.
    assert all(isinstance(item, HarnessDefinitionDeclaration) for item in payload)
    assert not any(hasattr(item, 'records') or hasattr(item, 'verifier') for item in payload)
    assert payload[0] not in (provider, view, view.records, view.verifier)


def test_owner_absent_provider_stays_discovery_only():
    """With no owner view the provider advertises discovery only: no prepare or start."""
    runtime = ClaudeCodeRuntimeProvider(definition_ref=DEFINITION, implementation_digest=DIGEST)
    assert isinstance(runtime, ClaudeCodeRuntimeProvider)
    assert runtime.descriptor.provider_id == 'claude'
    assert set(runtime.descriptor.supported_methods) == DISCOVERY_METHODS
    assert not ({'prepare', 'start'} & set(runtime.descriptor.supported_methods))


def test_registration_does_not_require_a_live_owner():
    assert ClaudeCodeServerPlugin(declaration()).build(context()).contributions is not None


def test_registration_ignores_environment_owner_attributes():
    """The plugin reads only the catalog: no Environment owner attribute is consulted."""
    frozen = declaration()
    for owner_ports in (None, object(), SimpleNamespace(provider_view=None)):
        environment = SimpleNamespace(environment_id=ENVIRONMENT_ID, owner_ports=owner_ports)
        ctx = ServerPluginContext(plugin_id='claude-code', data_root=None, ports={
            'execution.harness.catalog': catalog(),
            'core.binding': SimpleNamespace(environment=environment)})
        assert registration_payload(ClaudeCodeServerPlugin(frozen).build(ctx)) == (frozen,)


@pytest.mark.parametrize('field', ['records', 'verifier'])
def test_substituted_owner_records_or_verifier_is_refused(field):
    view = fresh_view()
    setattr(view, field, object())
    with pytest.raises(TypeError, match='frozen Claude Harness definition'):
        ClaudeCodeServerPlugin(view)


@pytest.mark.parametrize('mode', ['records', 'verifier', 'both'])
def test_provider_refuses_other_records_or_verifier_than_the_assembled_owner(mode):
    """The provider must bind the assembled owner's original records and verifier."""
    view = fresh_view()
    other = fresh_view()
    verifier = view.verifier if mode == 'records' else other.verifier
    records = view.records if mode == 'verifier' else other.records
    # The owner projection always holds the assembled pair; a provider built on a
    # substituted store or verifier is refused, never silently accepted.
    owner_port = SimpleNamespace(supported_methods=('recover',), records=view.records,
                                 verifier=view.verifier, recover=lambda *a: None)
    with pytest.raises(ClaudeProviderUnavailable, match='same original'):
        ClaudeCodeRuntimeProvider(definition_ref=DEFINITION, implementation_digest=DIGEST,
                                  verifier=verifier, unit_records=records, unit_port=owner_port)


def test_live_owner_or_old_provider_factory_cannot_register_as_a_definition():
    view = fresh_view()
    provider = live_provider(view)
    for value in (provider, view, lambda *a, **k: provider):
        with pytest.raises(TypeError, match='frozen Claude Harness definition'):
            ClaudeCodeServerPlugin(value)


def test_non_declaration_is_refused():
    for value in (None, object(), lambda *a, **k: None):
        with pytest.raises(TypeError, match='frozen Claude Harness definition'):
            ClaudeCodeServerPlugin(value)


def test_missing_original_catalog_refuses_before_registration():
    with pytest.raises(GuaranteeUnavailableError, match='original Harness catalog'):
        ClaudeCodeServerPlugin(declaration()).build(context(bound=False))
    with pytest.raises(GuaranteeUnavailableError, match='original Harness catalog'):
        ClaudeCodeServerPlugin(declaration()).build(
            ServerPluginContext(plugin_id='claude-code', data_root=None, ports={}))


def test_wrong_family_or_environment_definition_is_refused():
    # A foreign provider/definition family is refused at the declaration identity.
    for wrong in (declaration(provider_id='codex'), declaration(definition_id='codex')):
        with pytest.raises(ValueError, match='original Claude provider and definition identity required'):
            ClaudeCodeServerPlugin(wrong)
    # A definition from another namespace is refused against the bound catalog.
    with pytest.raises(GuaranteeUnavailableError, match='original namespace'):
        ClaudeCodeServerPlugin(declaration(namespace='env-foreign')).build(context())
